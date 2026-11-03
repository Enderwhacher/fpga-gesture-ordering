"""Model arithmetic coverage only; does not predict measured speedup."""
import json
from pathlib import Path
import onnx
from onnx import shape_inference,numpy_helper

ROOT=Path(__file__).resolve().parents[1]
model=shape_inference.infer_shapes(onnx.load(ROOT/'source/hagrid_mobilenetv3_large.onnx'))
shapes={v.name:[d.dim_value for d in v.type.tensor_type.shape.dim] for v in (*model.graph.value_info,*model.graph.input,*model.graph.output)}
weights={t.name:numpy_helper.to_array(t) for t in model.graph.initializer}
totals={'pointwise':0,'depthwise':0,'other':0};target=[]
for node in model.graph.node:
    if node.op_type!='Conv':continue
    w=weights[node.input[1]];out=shapes[node.output[0]]
    macs=int(out[0]*out[1]*out[2]*out[3]*w.shape[1]*w.shape[2]*w.shape[3])
    group=next((a.i for a in node.attribute if a.name=='group'),1)
    kind='depthwise' if group>1 and w.shape[1]==1 else ('pointwise' if w.shape[2:]==(1,1) else 'other')
    totals[kind]+=macs
    if node.name.startswith(('/features/features.5/','/features/features.6/')):target.append({'node':node.name,'kind':kind,'macs':macs})
total=sum(totals.values());selected=sum(row['macs'] for row in target)
assert selected==19772160
report={'scope':'Static Conv MAC coverage, not speedup; excludes non-Conv arithmetic','model_conv_macs':total,
    'model_conv_macs_by_kind':totals,'pointwise_fraction':totals['pointwise']/total,
    'target_blocks':[5,6],'target_conv_macs':selected,'target_fraction':selected/total,
    'old_single_dw_conv_macs':2352000,'coverage_ratio_vs_old_single_dw':selected/2352000,
    'target_convs':target,'run_input_bytes':125456,'run_output_bytes':125440,
    'parameter_loading':'Two 82848-byte banks once per overlay initialization; not sent with every frame',
    'speedup_status':'Board test required; standalone block timing and complete classifier timing are reported separately'}
(ROOT/'reports/target_selection.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='target_convs'},indent=2))
