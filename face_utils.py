import base64
import io
import math
import os
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
FACES_DIR = BASE_DIR / "data" / "faces"
MODEL_PATH = BASE_DIR / "data" / "db" / "lbph_model.yml"
FACES_DIR.mkdir(parents=True, exist_ok=True)

CONFIDENCE_ACCEPT_THRESHOLD = 72.0


def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees), returning meters.
    """
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 1)


def check_allowed_area(latitude, longitude):
    import database as db
    zone = db.get_active_zone()
    if not zone:
        return {
            "allowed": True,
            "distance_meters": 0.0,
            "radius_meters": 0.0,
            "zone_name": "Unrestricted Zone",
            "message": "No geofence area zone configured."
        }

    try:
        dist = calculate_haversine_distance(latitude, longitude, zone["lat"], zone["lng"])
        allowed = dist <= zone["radius_meters"]
        return {
            "allowed": allowed,
            "distance_meters": dist,
            "radius_meters": zone["radius_meters"],
            "zone_name": zone.get("name", "Area Zone"),
            "message": f"Inside {zone.get('name', 'Area Zone')} ({dist}m away)" if allowed else f"Outside {zone.get('name', 'Area Zone')} ({dist}m away, allowed radius is {zone['radius_meters']}m)"
        }
    except Exception as e:
        return {"allowed": False, "error": str(e), "distance_meters": 0.0, "radius_meters": 0.0, "zone_name": "Error"}


def is_in_allowed_area(latitude, longitude):
    res = check_allowed_area(latitude, longitude)
    return res.get("allowed", False)



def _ensure_model_dir():
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)


def _decode_frame(frame_data):
    if not frame_data:
        return None
    if frame_data.startswith("data:image"):
        header, encoded = frame_data.split(",", 1)
        if ";base64" in header:
            data = base64.b64decode(encoded)
            return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    return None


def save_face_sample(student_id, frame_data, sample_index=0):
    image = _decode_frame(frame_data)
    if image is None:
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    if len(faces) == 0:
        return False
    x, y, w, h = faces[0]
    face = gray[y:y + h, x:x + w]
    face = cv2.resize(face, (200, 200))
    student_dir = FACES_DIR / student_id
    student_dir.mkdir(parents=True, exist_ok=True)
    path = student_dir / f"sample_{sample_index}.jpg"
    success, encoded = cv2.imencode(".jpg", face)
    if not success:
        return False
    encoded.tofile(path)
    return True


def count_samples(student_id):
    student_dir = FACES_DIR / student_id
    if not student_dir.exists():
        return 0
    return len([p for p in student_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}])


def train_model():
    _ensure_model_dir()
    labels = []
    faces = []
    student_dirs = sorted([p for p in FACES_DIR.iterdir() if p.is_dir()])
    if not student_dirs:
        return {"ok": False, "error": "No face samples available"}
    for label, student_dir in enumerate(student_dirs):
        for sample_path in sorted(student_dir.glob("*.jpg")):
            image = cv2.imread(str(sample_path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            faces.append(image)
            labels.append(label)
    if len(faces) < 2:
        return {"ok": False, "error": "At least two face samples are required to train the model"}
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(faces, np.array(labels, dtype=np.int32))
    recognizer.write(str(MODEL_PATH))
    return {"ok": True, "trained": True, "samples": len(faces)}


def recognize(frame_data):
    image = _decode_frame(frame_data)
    if image is None:
        return {"face_found": False, "matched": False, "confidence": 0, "reason": "invalid-frame"}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    if len(faces) == 0:
        return {"face_found": False, "matched": False, "confidence": 0, "reason": "no-face"}
    x, y, w, h = faces[0]
    face = gray[y:y + h, x:x + w]
    face = cv2.resize(face, (200, 200))
    if not MODEL_PATH.exists():
        return {"face_found": True, "matched": False, "confidence": 0, "reason": "model-not-trained"}
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(MODEL_PATH))
    label, distance = recognizer.predict(face)
    student_dirs = sorted([p for p in FACES_DIR.iterdir() if p.is_dir()])
    student_id = student_dirs[label].name if 0 <= label < len(student_dirs) else None
    confidence = max(0.0, 100.0 - float(distance))
    matched = confidence >= CONFIDENCE_ACCEPT_THRESHOLD
    return {
        "face_found": True,
        "matched": matched,
        "confidence": round(confidence, 1),
        "student_id": student_id,
        "reason": "matched" if matched else "low-confidence",
    }

