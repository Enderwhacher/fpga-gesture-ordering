"""Reproducible CPU baseline: frozen HaGRID features + a new 4-class head.
Run with the existing hagrid_conversion/.venv Python. Never changes input ZIPs.
"""
import argparse
import csv
import hashlib
import io
import json
import random
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
import torch
import torchvision
from torch import nn

LABELS = ['open_palm', 'fist', 'victory', 'thumbs_up']
MEAN = np.array([.54, .499, .474], dtype=np.float32)
STD = np.array([.234, .235, .231], dtype=np.float32)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_dataset(path):
    with zipfile.ZipFile(path) as z:
        rows = list(csv.DictReader(io.StringIO(z.read('manifest.csv').decode('utf-8-sig'))))
        expected = json.loads(z.read('SHA256.json'))
        images, digests = [], []
        for row in rows:
            data = z.read(row['image'])
            digest = hashlib.sha256(data).hexdigest()
            assert digest == expected[row['image']], row['image']
            assert row['label'] in LABELS
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            assert frame is not None
            images.append(frame)
            digests.append(digest)
    return images, rows, digests

def preprocess(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    scale = 224. / max(h, w)
    nw, nh = max(1, round(w*scale)), max(1, round(h*scale))
    resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
    padded = np.full((224, 224, 3), 144, np.uint8)
    x, y = (224-nw)//2, (224-nh)//2
    padded[y:y+nh, x:x+nw] = resized
    return np.ascontiguousarray(((padded.astype(np.float32)/255-MEAN)/STD).transpose(2, 0, 1))

def features(model, images, augmented, batch):
    result = []
    variants = ['original', 'horizontal_flip', 'brightness_0.8'] if augmented else ['original']
    with torch.inference_mode():
        for variant in variants:
            for start in range(0, len(images), batch):
                blobs = []
                for im in images[start:start+batch]:
                    if variant == 'horizontal_flip':
                        im = cv2.flip(im, 1)
                    elif variant == 'brightness_0.8':
                        im = np.clip(im.astype(np.float32)*.8, 0, 255).astype(np.uint8)
                    blobs.append(preprocess(im))
                result.append(model(torch.from_numpy(np.stack(blobs))).detach().clone())
                if start % (batch*4) == 0:
                    print(f'Features {variant}: {min(start+batch,len(images))}/{len(images)}', flush=True)
    return torch.cat(result).clone()

def metrics(y, pred):
    cm = np.zeros((4, 4), dtype=int)
    for a, b in zip(y, pred):
        cm[int(a), int(b)] += 1
    recalls = np.divide(cm.diagonal(), cm.sum(1), out=np.zeros(4), where=cm.sum(1)>0)
    return dict(samples=int(cm.sum()), accuracy=float(np.mean(np.asarray(y)==np.asarray(pred))),
                macro_recall=float(recalls.mean()), per_class_recall=dict(zip(LABELS, recalls.tolist())),
                confusion_matrix_rows_true_columns_predicted=cm.tolist())

def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', type=Path, default=root/'gesture_round01_02_reviewed.zip')
    parser.add_argument('--validation', type=Path, default=root/'gesture_round03_validation.zip')
    parser.add_argument('--weights', type=Path, default=root/'hagrid_conversion/MobileNetV3_large.pth')
    parser.add_argument('--out', type=Path, default=root/'gesture4_training_run01')
    parser.add_argument('--epochs', type=int, default=200)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    random.seed(42); np.random.seed(42); torch.manual_seed(42)
    torch.set_num_threads(args.threads); cv2.setNumThreads(1)
    train_images, train_rows, train_hashes = read_dataset(args.train)
    val_images, val_rows, val_hashes = read_dataset(args.validation)
    assert not set(train_hashes) & set(val_hashes), 'Exact image leakage'
    assert not {r['session_id'] for r in train_rows} & {r['session_id'] for r in val_rows}, 'Session leakage'
    assert sha(args.weights) == '1dbbae25e891ead69497bcde5985d87adbe511c26d5e392898c0c3e7abaa3301', 'Unexpected checkpoint'
    model = torchvision.models.mobilenet_v3_large(weights=None, num_classes=34)
    model.load_state_dict(torch.load(args.weights, map_location='cpu', weights_only=True)['MODEL_STATE'], strict=True)
    old_head = model.classifier[3]
    model.classifier[3] = nn.Identity()
    model.eval().requires_grad_(False)
    print(f'Train {len(train_rows)} original images; validation {len(val_rows)} original images', flush=True)
    x_train = features(model, train_images, True, 16)
    x_val = features(model, val_images, False, 16)
    y_train_original = torch.tensor([LABELS.index(r['label']) for r in train_rows])
    y_train = y_train_original.repeat(3)
    y_val = torch.tensor([LABELS.index(r['label']) for r in val_rows])
    # Original 34-class top-1 mapped into task labels. Other classes are errors.
    original_labels = json.loads((root/'hagrid_conversion/hagrid_mnv3_board_test/model_meta.json').read_text())['labels']
    mapping = {'palm':0, 'fist':1, 'peace':2, 'peace_inverted':2, 'like':3}
    with torch.no_grad():
        old_pred = old_head(x_val).argmax(1).tolist()
    old_mapped = [mapping.get(original_labels[i], -1) for i in old_pred]
    original_accuracy = float(np.mean(np.array(old_mapped)==y_val.numpy()))
    head = nn.Linear(x_train.shape[1], 4)
    counts = torch.bincount(y_train, minlength=4).float()
    criterion = nn.CrossEntropyLoss(weight=counts.sum()/(4*counts))
    opt = torch.optim.AdamW(head.parameters(), lr=.003, weight_decay=.01)
    history, best_key, best_state, best_epoch = [], (-1., -float('inf')), None, 0
    for epoch in range(1, args.epochs+1):
        head.train()
        for idx in torch.randperm(len(y_train)).split(64):
            opt.zero_grad()
            loss = criterion(head(x_train[idx]), y_train[idx])
            loss.backward(); opt.step()
        head.eval()
        with torch.no_grad():
            vl = head(x_val)
            val_loss = float(nn.functional.cross_entropy(vl, y_val))
            stat = metrics(y_val.numpy(), vl.argmax(1).numpy())
        history.append(dict(epoch=epoch, val_loss=val_loss, **stat))
        key = (stat['macro_recall'], -val_loss)
        if key > best_key:
            best_key, best_epoch = key, epoch
            best_state = {k:v.detach().clone() for k,v in head.state_dict().items()}
        if epoch == 1 or epoch % 20 == 0:
            print(f'Epoch {epoch}: validation accuracy={stat["accuracy"]:.3f}, loss={val_loss:.4f}', flush=True)
    head.load_state_dict(best_state); head.eval()
    with torch.no_grad():
        vp = head(x_val).argmax(1).numpy()
        tp = head(x_train[:len(train_rows)]).argmax(1).numpy()
    model.classifier[3] = head
    torch.save(dict(model_state=model.state_dict(), labels=LABELS, best_epoch=best_epoch,
                    architecture='mobilenet_v3_large', seed=42), args.out/'best.pth')
    report = dict(method='Frozen pretrained backbone and 1280-d embedding; only final linear layer trained',
                  seed=42, epochs=args.epochs, selected_epoch=best_epoch, selection='validation macro recall; ties lower loss',
                  train_original_images=len(train_rows), validation_images=len(val_rows),
                  train_feature_views=len(y_train), augmentation=['original','horizontal_flip','brightness_0.8'],
                  training_original=metrics(y_train_original.numpy(), tp), validation=metrics(y_val.numpy(), vp),
                  original_34class_mapped_top1_validation_accuracy=original_accuracy,
                  original_mapping=mapping, original_unmapped_predictions=int(sum(i<0 for i in old_mapped)),
                  validation_by_hand={}, training_zip_sha256=sha(args.train), validation_zip_sha256=sha(args.validation),
                  source_checkpoint_sha256=sha(args.weights), wall_seconds=time.monotonic()-start,
                  limitations=['Validation used for checkpoint selection, not independent final test.',
                               'All 384 validation images retained, including 48 preliminary flags.',
                               'Same collection environment; correlated frames are not independent trials.',
                               'Four-class output does not detect empty scenes or unknown gestures.',
                               'No board test or FPGA acceleration performed.'])
    for hand in ['left','right']:
        ix = [i for i,r in enumerate(val_rows) if r['hand']==hand]
        report['validation_by_hand'][hand] = metrics(y_val[ix].numpy(), vp[ix])
    (args.out/'report.json').write_text(json.dumps(report, indent=2))
    (args.out/'history.json').write_text(json.dumps(history, indent=2))
    with (args.out/'validation_predictions.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f, fieldnames=['image','label','hand','quality_flags','prediction','correct'])
        writer.writeheader()
        for row,pred in zip(val_rows,vp):
            writer.writerow({k:row.get(k,'') for k in ['image','label','hand','quality_flags']} |
                            dict(prediction=LABELS[pred], correct=LABELS[pred]==row['label']))
    metadata = dict(labels=LABELS, input_shape=[1,3,224,224], color_order='RGB', mean=MEAN.tolist(),
                    std=STD.tolist(), pad_value=144, resize='Longest side 224, centered padding; OpenCV linear',
                    frame_orientation='Use the same corrected orientation as collected PNGs; no extra rotation in preprocess',
                    runtime='CPU baseline; no FPGA acceleration', board_tested=False)
    (args.out/'model_meta.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(report, indent=2), flush=True)

if __name__ == '__main__':
    main()
