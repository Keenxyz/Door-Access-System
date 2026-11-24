import json
import os
import time
from pathlib import Path

from enrollment_auth import require_enrollment_password

PROJECT = Path(__file__).resolve().parent.parent
if not require_enrollment_password(PROJECT / "dataset/.enrollment-auth.json"):
    raise SystemExit(1)

import cv2

YUNET_MODEL = str(PROJECT / "models/face_detection_yunet_2023mar.onnx")
SFACE_MODEL = str(PROJECT / "models/face_recognition_sface_2021dec.onnx")
DATABASE = PROJECT / "dataset/authorized_faces.json"

REQUIRED_SAMPLES = 5

# Load models
detector = cv2.FaceDetectorYN.create(
    YUNET_MODEL, "", (640, 480), 0.8, 0.3, 5000
)

recognizer = cv2.FaceRecognizerSF.create(
    SFACE_MODEL, ""
)

# Get person's name
name = input("Enter authorized person's name: ").strip()

if not name:
    print("Name cannot be empty.")
    raise SystemExit

# Load existing database without overwriting it
DATABASE.parent.mkdir(exist_ok=True)

if os.path.exists(DATABASE):
    with open(DATABASE, "r") as file:
        database = json.load(file)
else:
    database = {"users": []}

if any(u["name"].lower() == name.lower()
       for u in database["users"]):
    print("This person is already registered.")
    raise SystemExit

# Open camera
camera = cv2.VideoCapture(0, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(0)

if not camera.isOpened():
    camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("ERROR: Camera not detected.")
    raise SystemExit

samples = []
last_capture = 0

print("\nENROLLMENT STARTED")
print("Click the camera window first.")
print("Press S to capture.")
print("Press Q or ESC to cancel.")

try:
    while True:
        ret, frame = camera.read()

        if not ret:
            print("Cannot read camera.")
            break

        height, width = frame.shape[:2]
        detector.setInputSize((width, height))

        _, faces = detector.detect(frame)
        selected_face = None

        if faces is not None and len(faces) > 0:
            selected_face = max(
                faces,
                key=lambda f: f[2] * f[3]
            )

            x, y, w, h = selected_face[:4].astype(int)

            cv2.rectangle(
                frame, (x, y), (x+w, y+h),
                (0, 255, 0), 2
            )

            status = "FACE DETECTED"
            color = (0, 255, 0)
        else:
            status = "NO FACE DETECTED"
            color = (0, 0, 255)

        cv2.putText(
            frame, status, (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2
        )

        cv2.putText(
            frame,
            f"Samples: {len(samples)}/{REQUIRED_SAMPLES}",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
            (255, 255, 255), 2
        )

        cv2.putText(
            frame, "S = CAPTURE | Q = EXIT",
            (20, height - 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (255, 255, 255), 2
        )

        cv2.imshow("Face Enrollment", frame)

        key = cv2.waitKey(30)
        if key != -1:
            key = key & 0xFF

        if key in (ord("q"), ord("Q"), 27):
            print("Enrollment cancelled.")
            break

        elif key in (ord("s"), ord("S")):
            if selected_face is None:
                print("No face detected. Try again.")
                continue

            if time.time() - last_capture < 1:
                continue

            aligned_face = recognizer.alignCrop(
                frame, selected_face
            )

            feature = recognizer.feature(aligned_face)
            feature = feature.flatten()

            norm = np.linalg.norm(feature)
            if norm == 0:
                print("Could not process face. Try again.")
                continue

            feature = feature / norm
            samples.append(feature.tolist())
            last_capture = time.time()

            print(
                f"Captured {len(samples)}/{REQUIRED_SAMPLES}"
            )

            if len(samples) >= REQUIRED_SAMPLES:
                database["users"].append({
                    "name": name,
                    "embeddings": samples
                })

                with open(DATABASE, "w") as file:
                    json.dump(database, file, indent=4)

                print("\nENROLLMENT SUCCESSFUL!")
                print("Registered:", name)
                print("Database:", DATABASE)
                break

finally:
    camera.release()
    cv2.destroyAllWindows()
    cv2.waitKey(1)
