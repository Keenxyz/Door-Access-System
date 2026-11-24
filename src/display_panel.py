"""Display the unannotated camera feed on an optional SSD1306 OLED."""

from contextlib import suppress
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic

import cv2
import numpy as np

OLED_SIZES = {"128x64": (128, 64), "128x32": (128, 32)}
OLED_REFRESH = .20
OLED_STALE_AFTER = 2.0
DITHER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                  dtype=np.uint8) * 16 + 8
LABELS = {
    "SCANNING": "SCANNING FOR FACE...",
    "VERIFYING": "FACE DETECTED",
    "GRANTED": "ACCESS GRANTED",
    "DENIED": "ACCESS DENIED",
}


@dataclass(frozen=True)
class PanelState:
    status: str = "SCANNING"
    name: str | None = None
    relay: str = "DISABLED"
    prompt: str | None = None
    photo: np.ndarray | None = None


def render_panel(state):
    width, height = 480, 272
    image = np.full((height, width, 3), (28, 39, 25), dtype=np.uint8)
    white = (240, 244, 234)
    accent = {"GRANTED": (145, 232, 112), "DENIED": (140, 150, 251)}.get(state.status, (161, 219, 188))
    status = LABELS[state.status]
    relay = f"RELAY: {state.relay}"
    detail = " ".join((state.prompt or ("VERIFYING..." if state.status == "VERIFYING" else "")).split())
    if state.status in ("GRANTED", "DENIED"):
        detail = "NAME: " + " ".join((state.name or "UNKNOWN").split())

    def text(value, x, y, scale, color, limit):
        if not value:
            return
        font = cv2.FONT_HERSHEY_SIMPLEX
        thickness = 2
        value = value[:100]
        size = cv2.getTextSize(value, font, scale, thickness)[0][0]
        while size > limit and scale > .24:
            scale -= .02
            size = cv2.getTextSize(value, font, scale, thickness)[0][0]
        if size > limit:
            while value and cv2.getTextSize(value + "...", font, scale, thickness)[0][0] > limit:
                value = value[:-1]
            value += "..."
        cv2.putText(image, value, (x, y), font, scale, color, thickness, cv2.LINE_AA)

    cv2.rectangle(image, (0, 0), (width - 1, 54), (49, 77, 48), -1)
    text("SIMULATION", 18, 35, .73, white, width - 36)
    limit = width - 36 if state.photo is None else 292
    text(status, 18, 105, .85, accent, limit)
    text(detail, 18, 146, .62, white, limit)
    text(relay, 18, 226, .66, white, limit)
    if state.photo is not None:
        x, y, box_width, box_height = 326, 70, 135, 180
        h, w = state.photo.shape[:2]
        ratio = min(box_width / w, box_height / h)
        crop = cv2.resize(state.photo, (max(1, round(w * ratio)), max(1, round(h * ratio))),
                          interpolation=cv2.INTER_AREA)
        ch, cw = crop.shape[:2]
        x += (box_width - cw) // 2
        y += (box_height - ch) // 2
        image[y:y + ch, x:x + cw] = crop
        cv2.rectangle(image, (x, y), (x + cw - 1, y + ch - 1), accent, 2)
    return image


def render_oled_frame(frame, resolution):
    """Fit the entire camera frame and dither shades to the OLED's one-bit pixels."""
    width, height = OLED_SIZES[resolution]
    pixels = np.zeros((height, width), dtype=np.uint8)
    if frame is None:
        return pixels

    frame_height, frame_width = frame.shape[:2]
    scale = min(width / frame_width, height / frame_height)
    fitted_width = max(1, round(frame_width * scale))
    fitted_height = max(1, round(frame_height * scale))
    fitted = cv2.resize(frame, (fitted_width, fitted_height), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(fitted, cv2.COLOR_BGR2GRAY)
    thresholds = np.tile(DITHER, ((fitted_height + 3) // 4, (fitted_width + 3) // 4))
    x, y = (width - fitted_width) // 2, (height - fitted_height) // 2
    pixels[y:y + fitted_height, x:x + fitted_width] = (
        gray > thresholds[:fitted_height, :fitted_width]
    ).astype(np.uint8) * 255
    return pixels


class PanelOutput:
    """Use a single frame slot so I2C transfers cannot slow or queue recognition."""

    def __init__(self, resolution, address):
        self.resolution = resolution
        self.address = address
        self.stop = Event()
        self.latest = None, float("-inf")
        self.worker = Thread(target=self.run, name="door-panel", daemon=True)
        self.worker.start()

    def observe(self, frame):
        now = monotonic()
        if now - self.latest[1] >= OLED_REFRESH:
            self.latest = frame.copy(), now

    def run(self):
        serial = screen = None
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            from PIL import Image

            serial = i2c(port=1, address=self.address)
            width, height = OLED_SIZES[self.resolution]
            screen = ssd1306(serial, width=width, height=height)
            previous = object()
            print(f"SSD1306 camera monitor initialized at 0x{self.address:02x} ({width}x{height}).", flush=True)
            while not self.stop.is_set():
                frame, captured = self.latest
                if monotonic() - captured >= OLED_STALE_AFTER:
                    frame = None
                if frame is not previous:
                    pixels = render_oled_frame(frame, self.resolution)
                    screen.display(Image.fromarray(pixels).convert("1"))
                    previous = frame
                self.stop.wait(OLED_REFRESH)
        except Exception as error:
            print(f"SSD1306 unavailable. Recognition continues ({type(error).__name__}: {error}).", flush=True)
        finally:
            if screen is not None:
                with suppress(Exception):
                    screen.cleanup()
            elif serial is not None:
                with suppress(Exception):
                    serial.cleanup()

    def close(self):
        self.stop.set()
        self.worker.join(timeout=2)


def preview_oled(camera, resolution):
    window = "SSD1306 camera preview - " + resolution
    print("OLED webcam preview. Press Q or Esc to close.", flush=True)
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                raise RuntimeError("Camera stopped returning frames.")
            pixels = render_oled_frame(frame, resolution)
            preview = cv2.resize(pixels, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
            cv2.imshow(window, preview)
            if cv2.waitKey(round(OLED_REFRESH * 1000)) & 0xFF in (ord("q"), 27):
                return 0
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        cv2.destroyAllWindows()


def simulate_panel():
    face = np.full((160, 128, 3), (85, 98, 68), dtype=np.uint8)
    cv2.ellipse(face, (64, 76), (39, 53), 0, 0, 360, (147, 190, 225), -1)
    for x in (50, 77):
        cv2.circle(face, (x, 71), 4, (58, 52, 48), -1)
    cv2.ellipse(face, (64, 97), (14, 8), 0, 0, 180, (76, 82, 147), 2)
    scenes = (
        (2, PanelState(relay="LOCKED")),
        (2, PanelState("VERIFYING", relay="LOCKED", photo=face)),
        (5, PanelState("GRANTED", "Demo Resident", "UNLOCKED", photo=face)),
        (2, PanelState(relay="LOCKED")),
        (5, PanelState("DENIED", "UNKNOWN", "LOCKED", photo=face)),
    )
    duration = sum(seconds for seconds, _ in scenes)
    started = monotonic()
    window = "Door Access System - screen simulation"
    print("Display simulation. Press Q or Esc to close.", flush=True)
    last = None
    try:
        while True:
            elapsed = (monotonic() - started) % duration
            for seconds, state in scenes:
                if elapsed < seconds:
                    break
                elapsed -= seconds
            if state is not last:
                cv2.imshow(window, render_panel(state))
                last = state
            if cv2.waitKey(40) & 0xFF in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        cv2.destroyAllWindows()
