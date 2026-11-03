"""Full-network transfer learning; immutable source ZIPs, session-disjoint validation.

Starts again from original HaGRID weights, not the previous four-class checkpoint.
BN running statistics stay pretrained for the small correlated dataset; all affine
and convolution parameters are optimized during fine-tuning. No test-set claims.
"""
import argparse
import csv
import json
import random
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch
import torchvision
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as T
from torchvision.transforms import InterpolationMode

from train_gesture4 import LABELS, MEAN, STD, metrics, preprocess, read_dataset, sha


class Frames(Dataset):
    def __init__(self, frames, rows, augment=False):
        # Prepare the exact deployment letterbox once, before random augmentation.
        self.images = []
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            scale = 224 / max(h, w)
            nw, nh = round(w * scale), round(h * scale)
            image = np.full((224, 224, 3), 144, np.uint8)
            x, y = (224 - nw) // 2, (224 - nh) // 2
            image[y:y+nh, x:x+nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
            self.images.append(image)
        self.targets = [LABELS.index(row['label']) for row in rows]
        ops = [T.ToPILImage()]
        if augment:
            ops += [T.RandomHorizontalFlip(),
                    T.RandomAffine(degrees=12, translate=(.035, .035), scale=(.92, 1.04),
                                   interpolation=InterpolationMode.BILINEAR, fill=(144,144,144)),
                    T.ColorJitter(brightness=.22, contrast=.18, saturation=.12)]
        ops += [T.ToTensor(), T.Normalize(MEAN.tolist(), STD.tolist())]
        self.transform = T.Compose(ops)

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        return self.transform(self.images[index]), self.targets[index]


def evaluate(model, loader):
    model.eval()
    outputs, targets = [], []
    with torch.inference_mode():
        for x, y in loader:
            outputs.append(model(x)); targets.append(y)
    logits, y = torch.cat(outputs), torch.cat(targets)
    result = metrics(y.numpy(), logits.argmax(1).numpy())
    result['loss'] = float(nn.functional.cross_entropy(logits, y))
    return result, logits.argmax(1).numpy(), logits.numpy()


def group_metrics(rows, pred):
    result = {}
    for hand in ('left', 'right'):
        indexes = [i for i, row in enumerate(rows) if row.get('hand') == hand]
        result[hand] = metrics([LABELS.index(rows[i]['label']) for i in indexes], pred[indexes])
    return result


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=root/'gesture4_full_run02')
    parser.add_argument('--epochs', type=int, default=24)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--patience', type=int, default=7)
    parser.add_argument('--batch', type=int, default=16)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    random.seed(2026); np.random.seed(2026); torch.manual_seed(2026)
    torch.set_num_threads(args.threads); cv2.setNumThreads(1)
    paths = [root/'gesture_round01_02_reviewed.zip', root/'gesture_round03_validation.zip']
    tr_images, tr_rows, tr_hashes = read_dataset(paths[0])
    va_images, va_rows, va_hashes = read_dataset(paths[1])
    assert not set(tr_hashes) & set(va_hashes), 'Exact duplicate leakage'
    assert not {r['session_id'] for r in tr_rows} & {r['session_id'] for r in va_rows}, 'Session leakage'
    for rows in (tr_rows, va_rows):
        assert set(r['label'] for r in rows) == set(LABELS)
    train = Frames(tr_images, tr_rows, True)
    train_clean = Frames(tr_images, tr_rows)
    valid = Frames(va_images, va_rows)
    # Guard training/deployment normalization and letterbox equivalence.
    for i in (0, len(va_images)-1):
        np.testing.assert_allclose(valid[i][0].numpy(), preprocess(va_images[i]), atol=1e-6)
    del tr_images, va_images
    train_loader = DataLoader(train, batch_size=args.batch, shuffle=True, num_workers=0)
    val_loader = DataLoader(valid, batch_size=args.batch, shuffle=False, num_workers=0)
    clean_loader = DataLoader(train_clean, batch_size=args.batch, shuffle=False, num_workers=0)
    weights = root/'hagrid_conversion/MobileNetV3_large.pth'
    assert sha(weights) == '1dbbae25e891ead69497bcde5985d87adbe511c26d5e392898c0c3e7abaa3301'
    model = torchvision.models.mobilenet_v3_large(weights=None, num_classes=34)
    model.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True)['MODEL_STATE'])
    model.classifier[3] = nn.Linear(1280, 4)
    counts = torch.bincount(torch.tensor(train.targets), minlength=4).float()
    criterion = nn.CrossEntropyLoss(weight=counts.sum()/(4*counts), label_smoothing=.05)
    config = dict(seed=2026, architecture='mobilenet_v3_large', labels=LABELS,
                  train_images=len(train), validation_images=len(valid),
                  train_sessions=sorted({r['session_id'] for r in tr_rows}),
                  validation_sessions=sorted({r['session_id'] for r in va_rows}),
                  train_class_counts=dict(Counter(r['label'] for r in tr_rows)),
                  train_zip_sha256=sha(paths[0]), validation_zip_sha256=sha(paths[1]),
                  source_checkpoint_sha256=sha(weights), torch=torch.__version__,
                  torchvision=torchvision.__version__, device='cpu',
                  augmentation=['horizontal flip p=0.5', 'affine +/-12 deg, translate +/-3.5%, scale .92-1.04',
                                'brightness .22, contrast .18, saturation .12'],
                  warmup_epochs=args.warmup, finetune_max_epochs=args.epochs,
                  batch=args.batch, threads=args.threads, patience=args.patience,
                  all_network_parameters=sum(p.numel() for p in model.parameters()),
                  batchnorm='pretrained running statistics frozen; affine weights trainable in full stage',
                  selection='validation macro recall, tie lower unsmoothed cross entropy',
                  independent_test_available=False)
    (args.out/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(json.dumps(config, indent=2), flush=True)
    baseline = torchvision.models.mobilenet_v3_large(weights=None, num_classes=4)
    baseline.load_state_dict(torch.load(root/'gesture4_training_run01/best.pth', map_location='cpu', weights_only=True)['model_state'])
    baseline_stat, baseline_pred, _ = evaluate(baseline, val_loader)
    baseline_stat['by_hand'] = group_metrics(va_rows, baseline_pred)
    del baseline
    print('OLD MODEL VALIDATION', baseline_stat['accuracy'], flush=True)
    best_key, best_epoch, best_stage, history = (-1., -float('inf')), 0, None, []
    epoch_global = 0
    for stage, epochs in [('head_warmup', args.warmup), ('full_finetune', args.epochs)]:
        if stage == 'head_warmup':
            model.requires_grad_(False)
            model.classifier[3].requires_grad_(True)
            optimizer = torch.optim.AdamW(model.classifier[3].parameters(), lr=.001, weight_decay=.01)
        else:
            model.requires_grad_(True)
            optimizer = torch.optim.AdamW([
                {'params': model.features.parameters(), 'lr': 1e-5},
                {'params': model.avgpool.parameters(), 'lr': 1e-5},
                {'params': model.classifier[:3].parameters(), 'lr': 3e-5},
                {'params': model.classifier[3].parameters(), 'lr': 1e-4}], weight_decay=.01)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-6)
        stale = 0
        for local_epoch in range(1, epochs+1):
            epoch_global += 1
            epoch_start = time.monotonic()
            model.train()
            # Small batches and heavily correlated video frames must not overwrite BN statistics.
            for layer in model.modules():
                if isinstance(layer, nn.BatchNorm2d):
                    layer.eval()
            if stage == 'head_warmup':
                model.eval(); model.classifier[3].train()
            total_loss = 0.
            for step, (x, y) in enumerate(train_loader):
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(model(x), y)
                if not torch.isfinite(loss):
                    raise RuntimeError('Non-finite training loss')
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.)
                optimizer.step()
                total_loss += float(loss.detach()) * len(y)
            stat, _, _ = evaluate(model, val_loader)
            key = (stat['macro_recall'], -stat['loss'])
            improved = key > best_key
            if improved:
                best_key, best_epoch, best_stage, stale = key, epoch_global, stage, 0
                torch.save(dict(model_state=model.state_dict(), labels=LABELS,
                                architecture='mobilenet_v3_large', best_epoch=best_epoch,
                                stage=stage, seed=2026), args.out/'best.pth')
            else:
                stale += 1
            item = dict(epoch=epoch_global, stage=stage, stage_epoch=local_epoch,
                        train_augmented_loss=total_loss/len(train), validation=stat,
                        learning_rates=[g['lr'] for g in optimizer.param_groups],
                        seconds=time.monotonic()-epoch_start, selected=improved)
            history.append(item)
            (args.out/'history.json').write_text(json.dumps(history, indent=2), encoding='utf-8')
            print(f'EPOCH {epoch_global} {stage} {local_epoch}/{epochs}: val={stat["accuracy"]:.4f} '
                  f'loss={stat["loss"]:.4f} train_loss={item["train_augmented_loss"]:.4f} '
                  f'seconds={item["seconds"]:.1f} best={best_epoch}', flush=True)
            scheduler.step()
            if stage == 'full_finetune' and stale >= args.patience:
                print('EARLY STOP', flush=True)
                break
    checkpoint = torch.load(args.out/'best.pth', map_location='cpu', weights_only=True)
    model.load_state_dict(checkpoint['model_state'])
    validation, pred, logits = evaluate(model, val_loader)
    training, _, _ = evaluate(model, clean_loader)
    validation['by_hand'] = group_metrics(va_rows, pred)
    report = dict(method='Original HaGRID initialization; new head warmup then full-network fine-tuning',
                  selected_epoch=best_epoch, selected_stage=best_stage, epochs_run=len(history),
                  validation=validation, training_original=training, old_model_validation=baseline_stat,
                  validation_accuracy_delta=validation['accuracy']-baseline_stat['accuracy'],
                  wall_seconds=time.monotonic()-began, board_tested=False,
                  limitations=['Validation is used for model selection, NOT an independent test.',
                               'Only existing 722 images; consecutive frames correlated and backgrounds limited.',
                               'No additional samples or labels were invented; all validation images retained.',
                               'Full-frame four-class classification; no empty/unknown class; palm detector unchanged.',
                               'No board accuracy or latency claim.'])
    (args.out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    np.save(args.out/'validation_logits.npy', logits)
    with (args.out/'validation_predictions.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['image','session_id','label','hand','quality_flags','prediction','correct'])
        writer.writeheader()
        for row, p in zip(va_rows, pred):
            writer.writerow({k:row.get(k,'') for k in ['image','session_id','label','hand','quality_flags']} |
                            dict(prediction=LABELS[p], correct=LABELS[p]==row['label']))
    metadata = json.loads((root/'gesture4_training_run01/model_meta.json').read_text(encoding='utf-8'))
    metadata.update(training='full_network_finetune', board_tested=False)
    (args.out/'model_meta.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('COMPLETED', json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
