from pathlib import Path
import hashlib
import json
import cv2
import numpy as np

class HagridClassifier:
    def __init__(self, directory):
        directory = Path(directory)
        self.meta = json.loads((directory / 'model_meta.json').read_text(encoding='utf-8'))
        path = directory / 'hagrid_mobilenetv3_large.onnx'
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != self.meta['model_sha256']:
            raise RuntimeError('模型文件校验失败，请重新上传完整 ONNX 文件。')
        self.labels = self.meta['labels']
        self.mean = np.array(self.meta['mean'], dtype=np.float32)
        self.std = np.array(self.meta['std'], dtype=np.float32)
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    def preprocess(self, frame_bgr):
        if frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError('需要三通道 BGR 图像')
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = 224.0 / max(h, w)
        nw, nh = max(1, round(w*scale)), max(1, round(h*scale))
        resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        padded = np.full((224, 224, 3), self.meta['pad_value'], dtype=np.uint8)
        y, x = (224-nh)//2, (224-nw)//2
        padded[y:y+nh, x:x+nw] = resized
        value = (padded.astype(np.float32)/255.0-self.mean)/self.std
        return np.ascontiguousarray(value.transpose(2,0,1)[None])

    def logits(self, blob):
        self.net.setInput(blob)
        values = self.net.forward().reshape(-1)
        if len(values) != len(self.labels) or not np.isfinite(values).all():
            raise RuntimeError('模型输出维度或数值异常')
        return values

    def topk(self, logits, k=5):
        exp = np.exp(logits - np.max(logits))
        scores = exp / exp.sum()
        return [(self.labels[int(i)], float(scores[i]))
                for i in np.argsort(scores)[::-1][:k]]
