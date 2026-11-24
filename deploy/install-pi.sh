#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo on the Raspberry Pi." >&2
    exit 1
fi
if ! grep -aq 'Raspberry Pi' /proc/device-tree/model; then
    echo "This installer requires Raspberry Pi OS on a Raspberry Pi." >&2
    exit 1
fi
if systemctl is-active --quiet smart-door.service; then
    echo "Stop smart-door.service before reinstalling the application." >&2
    exit 1
fi

source_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
app=/opt/smart-door
config=/etc/smart-door
detector=face_detection_yunet_2023mar.onnx
recognizer=face_recognition_sface_2021dec.onnx
pad=anti-spoof-mn3.onnx

for file in "models/$detector" "models/$recognizer" dataset/authorized_faces.json; do
    if [ ! -s "$source_dir/$file" ]; then
        echo "Missing $file. Copy the models and enrollment data to the source directory first." >&2
        exit 1
    fi
done

python3 -B - "$source_dir" <<'PYTHON'
import sys
from pathlib import Path

import cv2
import gpiozero
import lgpio
import numpy as np

version = tuple(map(int, cv2.__version__.split(".")[:2]))
if version < (4, 8) or not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
    raise SystemExit("Install OpenCV 4.8 or later with YuNet and SFace support.")

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
from face_engine import FaceEngine

engine = FaceEngine(root / "models/face_detection_yunet_2023mar.onnx",
                    root / "models/face_recognition_sface_2021dec.onnx",
                    root / "dataset/authorized_faces.json", .363)
engine.detect(np.zeros((480, 640, 3), dtype=np.uint8))
feature = engine.recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
if feature.size != 128 or not np.isfinite(feature).all():
    raise SystemExit("The SFace model did not return a valid embedding.")
print("Validated OpenCV, YuNet, SFace and the enrollment database.")
PYTHON


for group in gpio video audio; do
    if ! getent group "$group" >/dev/null; then
        echo "Required device group is missing: $group." >&2
        exit 1
    fi
done
if ! id smart-door >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir /var/lib/smart-door \
        --shell /usr/sbin/nologin smart-door
fi
if [ "$(id -nG smart-door)" != smart-door ] || [ "$(id -u smart-door)" -eq 0 ]; then
    echo "The smart-door account must have only its dedicated primary group." >&2
    exit 1
fi

install -d -m 0755 -o root -g root "$app" "$app/src" "$app/models" "$app/deploy"
install -d -m 0750 -o root -g smart-door "$app/dataset"
install -m 0640 -g smart-door "$source_dir/dataset/authorized_faces.json" "$app/dataset/"
for module in recognize_face recognition_gate door_control display_panel face_engine supabase_events writer_credentials; do
    install -m 0644 "$source_dir/src/$module.py" "$app/src/"
done
install -m 0644 "$source_dir/models/$detector" "$source_dir/models/$recognizer" "$app/models/"
if [ -s "$source_dir/models/$pad" ]; then
    install -m 0644 "$source_dir/models/$pad" "$app/models/"
fi
install -m 0644 "$source_dir/deploy/wait-for-devices.sh" "$app/deploy/"

python3 -m venv --system-site-packages "$app/.venv"

install -d -m 0700 -o root -g root "$config"
if [ ! -e "$config/smart-door.env" ]; then
    install -m 0600 "$source_dir/deploy/smart-door.env.example" "$config/smart-door.env"
fi
if [ ! -e "$config/writer-password" ]; then
    install -m 0600 /dev/null "$config/writer-password"
fi
chown root:root "$config/smart-door.env" "$config/writer-password"
chmod 0600 "$config/smart-door.env" "$config/writer-password"

install -m 0644 "$source_dir/deploy/smart-door.service" /etc/systemd/system/smart-door.service
systemd-analyze verify /etc/systemd/system/smart-door.service
systemctl daemon-reload
systemctl enable smart-door.service
systemctl start --no-block smart-door.service
echo "Installed, enabled for boot, and queued for immediate startup."
echo "Check the current run: sudo journalctl -u smart-door.service -b"

