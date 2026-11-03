"""Export complete features.5+features.6, keeping the original classifier intact."""
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import onnx
from onnx import helper,numpy_helper,shape_inference,utils
import onnxruntime as ort

ROOT=Path(__file__).resolve().parents[1]
WS=ROOT.parent
MODEL=ROOT/'source/hagrid_mobilenetv3_large.onnx'
if not MODEL.exists():MODEL=WS/'gesture4_accel_v2/source/hagrid_mobilenetv3_large.onnx'
MODEL_SHA='568660b57f4cd01cacae40d64df9124e9194c7fbcc42f8245839eb691badf741'
X='/features/features.4/block/block.3/block.3.0/Conv_output_0'
Y='/features/features.6/Add_output_0'
SHAPE=(1,40,28,28)
PARAM_WORDS=20712


def compare(actual,expected,atol=1e-4,rtol=1e-4):
    assert actual.shape==expected.shape and np.isfinite(actual).all() and np.isfinite(expected).all()
    delta=np.abs(actual.astype(np.float64)-expected.astype(np.float64))
    bad=delta>atol+rtol*np.abs(expected.astype(np.float64))
    result={'passed':not bool(bad.any()),'elements':int(actual.size),'max_abs_error':float(delta.max()),'bad_elements':int(bad.sum())}
    assert result['passed'],result
    return result


def reference(x,blocks):
    """Independent NumPy equations; no ONNX/OpenCV execution of target operators."""
    for p in blocks:
        original=x.copy()
        z=np.einsum('oc,nchw->nohw',p['expand_w'][:,:,0,0],x,optimize=True)+p['expand_b'][None,:,None,None]
        z=np.maximum(z,0).astype(np.float32)
        padded=np.pad(z,((0,0),(0,0),(2,2),(2,2)))
        dw=np.broadcast_to(p['depthwise_b'][None,:,None,None],z.shape).copy()
        for ky in range(5):
            for kx in range(5): dw+=padded[:,:,ky:ky+28,kx:kx+28]*p['depthwise_w'][:,0,ky,kx][None,:,None,None]
        dw=np.maximum(dw,0).astype(np.float32)
        mean=dw.mean(axis=(2,3),keepdims=True,dtype=np.float32)
        hidden=np.maximum(np.einsum('oc,nchw->nohw',p['se1_w'][:,:,0,0],mean,optimize=True)+p['se1_b'][None,:,None,None],0)
        gate=np.einsum('oc,nchw->nohw',p['se2_w'][:,:,0,0],hidden,optimize=True)+p['se2_b'][None,:,None,None]
        gate=np.clip(gate*np.float32(1/6)+np.float32(.5),0,1).astype(np.float32)
        scaled=(dw*gate).astype(np.float32)
        x=(np.einsum('oc,nchw->nohw',p['project_w'][:,:,0,0],scaled,optimize=True)+p['project_b'][None,:,None,None]+original).astype(np.float32)
    return x


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest()==MODEL_SHA
    for folder in ('source','export/models','export/params','export/cases','reports'): (ROOT/folder).mkdir(parents=True,exist_ok=True)
    import shutil
    for name in ('hagrid_mobilenetv3_large.onnx','model_meta.json','hagrid_runtime.py'):
        if (MODEL.parent/name).resolve()!=(ROOT/'source'/name).resolve():
            shutil.copyfile(MODEL.parent/name,ROOT/'source'/name)
    model=shape_inference.infer_shapes(onnx.load(MODEL),strict_mode=True)
    constants={v.name:numpy_helper.to_array(v) for v in model.graph.initializer}
    nodes=list(model.graph.node); byname={n.name:n for n in nodes}
    blocks=[]; keys=('expand','depthwise','se1','se2','project')
    suffixes=('block.0/block.0.0','block.1/block.1.0','block.2/fc1','block.2/fc2','block.3/block.3.0')
    for bank,feature in enumerate((5,6)):
        params={}
        for key,suffix in zip(keys,suffixes):
            node=byname[f'/features/features.{feature}/block/{suffix}/Conv']
            params[key+'_w']=constants[node.input[1]].copy(); params[key+'_b']=constants[node.input[2]].copy()
            attrs={a.name:helper.get_attribute_value(a) for a in node.attribute}
            if key=='depthwise': assert attrs['group']==120 and attrs['kernel_shape']==[5,5] and attrs['pads']==[2,2,2,2]
            else: assert attrs['group']==1 and attrs['kernel_shape']==[1,1]
            assert attrs['strides']==[1,1] and attrs['dilations']==[1,1]
        for key,shape in (('expand_w',(120,40,1,1)),('depthwise_w',(120,1,5,5)),('se1_w',(32,120,1,1)),('se2_w',(120,32,1,1)),('project_w',(40,120,1,1))):
            assert params[key].shape==shape
        activation=byname[f'/features/features.{feature}/block/block.2/scale_activation/HardSigmoid']
        attrs={a.name:helper.get_attribute_value(a) for a in activation.attribute}
        assert abs(attrs.get('alpha',.2)-1/6)<1e-7 and attrs.get('beta',.5)==.5
        blocks.append(params)
        packet=np.concatenate([params[k+'_w'].ravel() for k in keys]+[params[k+'_b'].ravel() for k in keys]).astype('<f4')
        assert packet.size==PARAM_WORDS
        packet.tofile(ROOT/f'export/params/block{bank}.bin')
        np.savez(ROOT/f'export/params/block{bank}.npz',**params)
    extractor=utils.Extractor(model)
    exports={'prefix':extractor.extract_model(['image'],[X]),'blocks':extractor.extract_model([X],[Y]),
             'suffix':extractor.extract_model([Y],['logits'])}
    assert len(exports['blocks'].graph.node)==24
    for name,sub in exports.items():
        onnx.checker.check_model(sub); onnx.save(sub,ROOT/f'export/models/{name}.onnx')
    values={v.name:v for v in [*model.graph.value_info,*model.graph.input,*model.graph.output]}
    assert tuple(d.dim_value for d in values[X].type.tensor_type.shape.dim)==SHAPE
    assert tuple(d.dim_value for d in values[Y].type.tensor_type.shape.dim)==SHAPE
    opt=ort.SessionOptions(); opt.intra_op_num_threads=2; opt.inter_op_num_threads=1
    sessions={name:ort.InferenceSession(sub.SerializeToString(),opt,providers=['CPUExecutionProvider']) for name,sub in exports.items()}
    tapped=copy.deepcopy(model)
    tapped.graph.output.extend([copy.deepcopy(values[X]),copy.deepcopy(values[Y])])
    full=ort.InferenceSession(tapped.SerializeToString(),opt,providers=['CPUExecutionProvider'])
    nets={name:cv2.dnn.readNetFromONNX(str(ROOT/f'export/models/{name}.onnx')) for name in exports}
    for net in nets.values():
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV); net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    inputs={}
    for name in ('black','gradient','seeded_noise'):
        path=ROOT/f'export/cases/{name}/model_input.npy'
        if not path.exists():path=WS/f'gesture4_accel_v2/export/cases/{name}/model_input.npy'
        inputs[name]=np.load(path,allow_pickle=False)
    spec=importlib.util.spec_from_file_location('block_export_cpu',MODEL.parent/'hagrid_runtime.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    cpu=module.HagridClassifier(MODEL.parent)
    real_blob=ROOT/'export/cases/real_frame/model_input.npy'
    inputs['real_frame']=np.load(real_blob,allow_pickle=False) if real_blob.exists() else cpu.preprocess(cv2.imread(str(WS/'gesture_order_accel_round2_v1/inputs/fixed_frame.png')))
    report={'passed':False,'board_tested':False,'cases':[],'reference':'Independent NumPy full-block equations + ORT + OpenCV split'}
    names=[]
    for name,blob in inputs.items():
        got=dict(zip([v.name for v in tapped.graph.output],full.run(None,{'image':blob})))
        x=got[X]; expected=got[Y]; checks={}
        checks['numpy_blocks']=compare(reference(x,blocks),expected)
        checks['ort_prefix']=compare(sessions['prefix'].run(None,{'image':blob})[0],x)
        checks['ort_blocks']=compare(sessions['blocks'].run(None,{X:x})[0],expected)
        checks['ort_suffix']=compare(sessions['suffix'].run(None,{Y:expected})[0],got['logits'])
        nets['prefix'].setInput(blob); cvx=nets['prefix'].forward()
        nets['blocks'].setInput(cvx); cvy=nets['blocks'].forward()
        checks['opencv_blocks']=compare(cvy,expected)
        nets['suffix'].setInput(cvy,Y); checks['opencv_split_logits']=compare(nets['suffix'].forward(),got['logits'])
        case=ROOT/'export/cases'/name; case.mkdir(exist_ok=True)
        for key,value in (('input',x),('golden_output',expected),('model_input',blob),('model_logits',got['logits'])):
            np.save(case/(key+'.npy'),value,allow_pickle=False)
            if key in ('input','golden_output'): value.astype('<f4').tofile(case/(key+'.bin'))
        names.append(name); report['cases'].append({'name':name,'checks':checks})
        print('BLOCK_EXPORT_PASS',name,flush=True)
    # Additional boundary/numeric vectors, including an exact zero-parameter
    # identity path used to prove coefficient replacement in C/RTL simulation.
    for name,x in (('zeros',np.zeros(SHAPE,np.float32)),('random',np.random.default_rng(563).normal(0,.2,SHAPE).astype(np.float32))):
        expected=sessions['blocks'].run(None,{X:x})[0]; compare(reference(x,blocks),expected)
        case=ROOT/'export/cases'/name; case.mkdir(exist_ok=True)
        for key,value in (('input',x),('golden_output',expected)):
            np.save(case/(key+'.npy'),value,allow_pickle=False); value.astype('<f4').tofile(case/(key+'.bin'))
        names.append(name)
    (ROOT/'export/case_list.txt').write_text('\n'.join(names)+'\n')
    params={'release':'gesture_blocks56_fp32_pw16_v2','source_model_sha256':MODEL_SHA,'input_shape':list(SHAPE),'output_shape':list(SHAPE),
            'input_tensor':X,'output_tensor':Y,'carry_tensors':[],'onnx_nodes':24,'blocks':[5,6],
            'parameter_words_per_block':PARAM_WORDS,'frame_words':31360,'weight_residency':'Two parameter banks loaded once, retained in PL until reconfiguration',
            'arithmetic':'FP32; no model quantization; includes SE and both residual additions',
            'macs':19772160,'protocol_magic':0x47534232,'protocol_version':1}
    (ROOT/'export/block_params.json').write_text(json.dumps(params,indent=2)+'\n')
    report['passed']=True
    (ROOT/'export/validation_report.json').write_text(json.dumps(report,indent=2)+'\n')
    exported=[p for p in (ROOT/'export').rglob('*') if p.is_file() and p.name!='export_manifest.json']
    (ROOT/'export/export_manifest.json').write_text(json.dumps({'sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in exported}},indent=2)+'\n')
    print('BLOCKS56_EXPORT_OK',len(names),'vectors; 24 ONNX nodes; FP32')


if __name__=='__main__': main()
