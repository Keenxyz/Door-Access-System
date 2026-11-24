"""YuNet detection, SFace embeddings, and an optional Open Model Zoo PAD model."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2
import numpy as np

PAD_SHA384 = "6de4534964b723397b3e8c995cadcf43bc007cc2f9930b95ae25f76adccece5d1d4d058d0b15117b9e4a9f758424f92a"


def save_enrollments(path, database):
    """Replace the enrollment file only after writing and flushing all embeddings."""
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(database, file, indent=4, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def face_crop(frame, face):
    height, width = frame.shape[:2]
    x, y, w, h = face[:4].astype(int)
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + w), min(height, y + h)
    return frame[top:bottom, left:right] if right > left and bottom > top else None


def photo_jpeg(frame, face):
    crop = face_crop(frame, face)
    if crop is None:
        return None
    height, width = crop.shape[:2]
    if max(height, width) > 640:
        scale = 640 / max(height, width)
        crop = cv2.resize(crop, (max(1, round(width * scale)), max(1, round(height * scale))),
                          interpolation=cv2.INTER_AREA)
    ok, image = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return image.tobytes() if ok else None


def face_yaw(face):
    left_eye = face[4:6]
    right_eye = face[6:8]
    nose_x = face[8]
    eye_distance = abs(float(left_eye[0] - right_eye[0]))
    if eye_distance < 12:
        return None
    return float((nose_x - (left_eye[0] + right_eye[0]) / 2) / eye_distance)


class FaceEngine:
    def __init__(self, yunet_path, sface_path, enrollment_path, threshold):
        self.threshold = threshold
        with enrollment_path.open(encoding="utf-8") as file:
            users = json.load(file).get("users", [])
        self.names = []
        templates = []
        for user in users:
            for value in user["embeddings"]:
                vector = np.asarray(value, dtype=np.float32).reshape(-1)
                norm = np.linalg.norm(vector)
                if vector.shape == (128,) and np.isfinite(norm) and norm > 0:
                    templates.append(vector / norm)
                    self.names.append(user["name"])
        if not templates:
            raise ValueError("No valid SFace enrollments. Run enroll_face.py first.")
        self.templates = np.stack(templates)
        self.detector = cv2.FaceDetectorYN.create(str(yunet_path), "", (640, 480), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(sface_path), "")
        self.size = (640, 480)

    def detect(self, frame):
        size = (frame.shape[1], frame.shape[0])
        if size != self.size:
            self.detector.setInputSize(size)
            self.size = size
        _, faces = self.detector.detect(frame)
        return [] if faces is None else faces

    def recognize(self, frame, face):
        aligned = self.recognizer.alignCrop(frame, face)
        feature = self.recognizer.feature(aligned).flatten()
        norm = np.linalg.norm(feature)
        if not np.isfinite(norm) or norm == 0:
            return None, -1.0
        scores = self.templates @ (feature / norm)
        index = int(np.argmax(scores))
        score = float(np.clip(scores[index], -1, 1))
        return (self.names[index] if score >= self.threshold else None), score


class PassiveLiveness:
    MEAN = np.array([151.2405, 119.5950, 107.8395], dtype=np.float32)
    SCALE = np.array([63.0105, 56.4570, 55.0035], dtype=np.float32)

    def __init__(self, model, threshold):
        with model.open("rb") as file:
            if hashlib.file_digest(file, "sha384").hexdigest() != PAD_SHA384:
                raise ValueError("Use the verified Open Model Zoo anti-spoof-mn3.onnx model.")
        self.network = cv2.dnn.readNetFromONNX(str(model))
        self.threshold = threshold
        self.score(np.zeros((128, 128, 3), dtype=np.uint8))

    def score(self, crop):
        rgb = cv2.cvtColor(cv2.resize(crop, (128, 128)), cv2.COLOR_BGR2RGB).astype(np.float32)
        tensor = np.ascontiguousarray(((rgb - self.MEAN) / self.SCALE).transpose(2, 0, 1)[None])
        self.network.setInput(tensor)
        output = self.network.forward().reshape(-1)
        if (output.shape != (2,) or not np.all(np.isfinite(output))
                or np.any(output < 0) or np.any(output > 1) or not np.isclose(output.sum(), 1, atol=.02)):
            raise ValueError("Unexpected output from the anti-spoofing model.")
        return float(output[0])

    def allows(self, frame, face):
        crop = face_crop(frame, face)
        if crop is None or min(crop.shape[:2]) < 60:
            return False
        return self.score(crop) >= self.threshold
