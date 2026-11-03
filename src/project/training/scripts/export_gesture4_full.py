"""Export and audit full-network run, without modifying the old board package."""
import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'gesture4_export_deps02'))
import onnx
import cv2
import numpy as np
import torch
import torchvision
from train_gesture4 import LABELS, preprocess, read_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, default=ROOT/'gesture4_full_run02')
    args = parser.parse_args()
    run = args.run
    report = json.loads((run/'report.json').read_text(encoding='utf-8'))
    torch.set_num_threads(4); cv2.setNumThreads(2)
    checkpoint = torch.load(run/'best.pth', map_location='cpu', weights_only=True)
    assert checkpoint['labels'] == LABELS
    model = torchvision.models.mobilenet_v3_large(weights=None, num_classes=4)
    model.load_state_dict(checkpoint['model_state'], strict=True)
    model.eval()
    board = run/'gesture4_model_v2'
    board.mkdir(exist_ok=False)
    dest = board/'hagrid_mobilenetv3_large.onnx'
    torch.onnx.export(model, torch.zeros(1,3,224,224), dest,
                      input_names=['image'], output_names=['logits'],
                      opset_version=13, do_constant_folding=True, dynamo=False)
    graph = onnx.load(dest)
    onnx.checker.check_model(graph)
    assert [d.dim_value for d in graph.graph.input[0].type.tensor_type.shape.dim] == [1,3,224,224]
    assert [d.dim_value for d in graph.graph.output[0].type.tensor_type.shape.dim] == [1,4]
    meta = json.loads((run/'model_meta.json').read_text(encoding='utf-8'))
    meta.update(model='HaGRID MobileNetV3-Large four-class full-network fine-tuning',
                model_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                output_classes=4, board_tested=False)
    (board/'model_meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    shutil.copyfile(ROOT/'gesture4_training_run01/gesture4_model/hagrid_runtime.py', board/'hagrid_runtime.py')
    sys.path.insert(0, str(board))
    from hagrid_runtime import HagridClassifier
    classifier = HagridClassifier(board)
    images, rows, _ = read_dataset(ROOT/'gesture_round03_validation.zip')
    cached_logits = np.load(run/'validation_logits.npy')
    maximum, matched, correct, times = 0., 0, 0, []
    with torch.inference_mode():
        for i, (frame, row) in enumerate(zip(images, rows)):
            blob = classifier.preprocess(frame)
            np.testing.assert_allclose(blob[0], preprocess(frame), atol=1e-6)
            reference = model(torch.from_numpy(blob)).numpy().reshape(-1)
            began = time.perf_counter()
            actual = classifier.logits(blob)
            times.append((time.perf_counter()-began)*1000)
            np.testing.assert_allclose(actual, reference, rtol=5e-4, atol=5e-4)
            np.testing.assert_allclose(reference, cached_logits[i], rtol=5e-4, atol=5e-4)
            maximum = max(maximum, float(np.max(np.abs(actual-reference))))
            matched += int(actual.argmax()==reference.argmax())
            correct += int(LABELS[int(actual.argmax())]==row['label'])
            assert classifier.topk(actual, 1)[0][0] == LABELS[int(actual.argmax())]
            if (i+1)%96 == 0:
                print(f'EXPORT VERIFIED {i+1}/{len(rows)}', flush=True)
    assert matched == len(rows)
    assert abs(correct/len(rows)-report['validation']['accuracy']) < 1e-10
    original = torch.load(ROOT/'hagrid_conversion/MobileNetV3_large.pth', map_location='cpu', weights_only=True)['MODEL_STATE']
    trainable = dict(model.named_parameters())
    feature_keys = [key for key in trainable if key.startswith('features.')]
    changed = [key for key in feature_keys if not torch.equal(checkpoint['model_state'][key], original[key])]
    assert len(changed) == len(feature_keys), 'Selected model did not update the entire feature extractor'
    verify = dict(images=len(rows), matched_top1=matched, correct=correct,
                  max_abs_logit_error=maximum, onnx=onnx.__version__, opencv=cv2.__version__,
                  feature_parameter_tensors_changed=len(changed), feature_parameter_tensors_total=len(feature_keys),
                  desktop_only_forward_median_ms=float(np.median(times[3:])),
                  desktop_threads=2, board_tested=False, board_latency_measured=False,
                  note='Desktop forward time is not board performance or full pipeline FPS.')
    (run/'export_verification.json').write_text(json.dumps(verify, indent=2), encoding='utf-8')
    print(json.dumps(verify, indent=2), flush=True)


if __name__ == '__main__':
    main()
