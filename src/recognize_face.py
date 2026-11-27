"""Recognize faces, drive optional Pi outputs, and record access decisions."""

import csv
import math
import os
import signal
import sqlite3
from argparse import ArgumentParser, ArgumentTypeError
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from uuid import uuid4

from door_control import DoorController, GpioOutputs, PULSE_SECONDS, SimulatedOutputs, Speaker
from recognition_gate import Observation, RecognitionGate
from supabase_events import (
    SupabaseEvents, report_supabase_error, setup_windows_writer, sync_saved_events,
)

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
DATABASE = ROOT / "dataset/authorized_faces.json"
LOG_FILE = ROOT / "access_logs.csv"
OUTBOX = ROOT / "door_event_outbox.sqlite3"
PHOTOS = ROOT / "event_photos"


def state_path(default, directory):
    return directory / default.name if directory is not None else default


def camera_source(value):
    if value.isascii() and value.isdigit():
        return int(value)
    if value.startswith("/dev/") and ".." not in Path(value).parts:
        return value
    raise ArgumentTypeError("Use a camera index or a Linux video device under /dev.")


def settings(argv=None):
    parser = ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="Run synthetic grant and denial without hardware or cloud writes.")
    mode.add_argument("--relay-bench", action="store_true", help="Pulse the GPIO relay with the solenoid load disconnected.")
    mode.add_argument("--sync-pending", action="store_true", help="Upload saved scans without opening the camera.")
    mode.add_argument("--setup-writer", action="store_true", help="Verify and save a Supabase writer login for this Windows account.")
    cloud = parser.add_mutually_exclusive_group()
    cloud.add_argument("--supabase", action="store_true", help="Require configured Supabase sync without prompting.")
    cloud.add_argument("--local-only", action="store_true", help="Log without uploading to Supabase.")
    parser.add_argument("--hardware", action="store_true", help="Enable GPIO LEDs and speaker on the Pi.")
    parser.add_argument("--relay-demo", action="store_true", help="Test face-triggered relay without a connected lock.")
    parser.add_argument("--enable-unlock", action="store_true", help="Enable the installed relay after confirming wiring and liveness.")
    parser.add_argument("--relay-active", choices=("low", "high"), help="The signal level that energizes the relay.")
    parser.add_argument("--lock-type", choices=("power-to-lock", "power-to-unlock"), help="Verified power behavior of the installed lock.")
    parser.add_argument("--pad-model", type=Path, help="Path to the official anti-spoof-mn3 ONNX model.")
    parser.add_argument("--pad-threshold", type=float, default=.90)
    parser.add_argument("--passive-only", action="store_true", help="Use passive anti-spoofing without head-turn challenges (testing only).")
    parser.add_argument("--liveness-seconds", type=float, default=18)
    parser.add_argument("--threshold", type=float, default=.363, help="SFace cosine similarity threshold.")
    parser.add_argument("--confirm-frames", type=int, default=3)
    parser.add_argument("--leave-seconds", type=float, default=1.2, help="Time an individual face must be out of view before starting a new visit.")
    parser.add_argument("--unlock-cooldown", type=float, default=8)
    parser.add_argument("--notification-cooldown", type=float, default=30)
    parser.add_argument("--capture-unknown", action="store_true", help="Capture one cropped JPEG per confirmed unknown visitor.")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--no-preview", action="store_true", help="Run without the OpenCV window, suitable for SSH.")
    parser.add_argument("--camera", type=camera_source, default=0, help="OpenCV camera index or Linux video device path.")
    parser.add_argument("--state-dir", type=Path, help="Directory for runtime logs, the upload queue, and local photos.")
    parser.add_argument("--offline-first", action="store_true", help="Start the camera without an initial cloud connection check.")
    args = parser.parse_args(argv)
    if args.state_dir is not None:
        args.state_dir = args.state_dir.resolve()

    for name in ("leave_seconds", "unlock_cooldown", "notification_cooldown", "liveness_seconds"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive and finite.")
    if args.confirm_frames < 1 or not -1 <= args.threshold <= 1 or not 0 < args.pad_threshold <= 1:
        parser.error("Use a positive frame count, threshold in [-1, 1], and PAD threshold in (0, 1].")
    if args.relay_bench and not args.relay_active:
        parser.error("--relay-bench requires the tested --relay-active high or low setting.")
    if args.enable_unlock and (
        not args.hardware or not args.relay_active or not args.lock_type or not args.pad_model
        or args.confirm_frames < 3 or args.threshold <= 0
        or args.simulate or args.relay_bench or args.sync_pending or args.setup_writer
    ):
        parser.error("--enable-unlock requires Pi hardware, a tested relay polarity, confirmed lock type, "
                     "the PAD model, at least three consecutive frames, and a positive threshold.")
    if args.hardware and args.simulate:
        parser.error("--simulate does not run with --hardware.")
    if args.enable_unlock and args.no_preview and args.no_audio:
        parser.error("Provide a preview or speaker for the liveness prompts.")
    if args.passive_only and not args.pad_model:
        parser.error("--passive-only requires --pad-model.")
    if args.passive_only and args.enable_unlock:
        parser.error("Passive-only mode is not approved for relay unlocking.")
    if args.relay_demo and (
        not args.hardware or not args.relay_active or not args.pad_model
        or args.enable_unlock or args.simulate or args.relay_bench
        or args.sync_pending or args.setup_writer
    ):
        parser.error("Relay demo requires hardware, relay polarity, PAD and no installed lock.")
    return args


def open_cloud(args):
    if args.local_only:
        print("Local-only mode. Saving access events to CSV.")
        return None

    try:
        cloud = SupabaseEvents.from_environment(state_path(OUTBOX, args.state_dir), background=False)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
        cloud = None
        print("Supabase configuration or queue is unavailable.")

    if cloud is None:
        if args.supabase:
            raise RuntimeError("Configure the Supabase writer before using --supabase.")
        print("Recognition will save events to CSV only.")
        return None

    if args.offline_first:
        cloud.start()
        print(f"Supabase queue enabled for {cloud.url}. Uploads retry in the background.")
        return cloud

    try:
        cloud.verify_writer()
    except HTTPError as error:
        if 400 <= error.code < 500 and error.code not in (408, 429):
            report_supabase_error(error)
            if args.supabase:
                raise RuntimeError("Check the saved Supabase writer credentials and pairing.") from None
            print("Recognition will save events to CSV only.")
            return None
        error.close()
        print("Supabase unavailable. The PC will queue events and retry.")
    except (OSError, ValueError, KeyError):
        print("Could not verify the PC writer. The PC will queue events and retry.")
    else:
        print("Supabase PC writer verified.")
    cloud.start()
    print(f"Supabase sync enabled for {cloud.url}.")
    return cloud


def log_access(decision, cloud, *, picture=None, lock_command=None, state_dir=None):
    log_file = state_path(LOG_FILE, state_dir)
    timestamp = datetime.now().astimezone()
    score = round(decision.score, 4)
    if not log_file.exists() or not log_file.stat().st_size:
        with log_file.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(["Date and Time", "Name", "Result", "Similarity"])
    with log_file.open("a", newline="", encoding="utf-8") as file:
        csv.writer(file).writerow([timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                                  decision.name, decision.result, score])
    print(timestamp.isoformat(timespec="seconds"), decision.result, decision.name, score, flush=True)
    if cloud is not None:
        try:
            cloud.enqueue(timestamp.astimezone(timezone.utc), decision.name, decision.result, score,
                          notify=decision.notify, lock_command=lock_command, photo=picture)
            return
        except (OSError, sqlite3.Error):
            print("Could not queue this scan for Supabase. The CSV entry was saved.", flush=True)
    if picture:
        photos = state_path(PHOTOS, state_dir)
        photos.mkdir(mode=0o700, exist_ok=True)
        (photos / f"{uuid4()}.jpg").write_bytes(picture)


def controller_for(args, *, simulate=False, bench=False):
    relay_enabled = simulate or bench or args.enable_unlock or args.relay_demo
    if simulate or not (args.hardware or bench):
        outputs = SimulatedOutputs(verbose=simulate)
    else:
        model = Path("/proc/device-tree/model")
        if not model.is_file() or "Raspberry Pi" not in model.read_text(errors="ignore"):
            raise RuntimeError("GPIO mode requires a Raspberry Pi. Use --simulate on Windows.")
        if args.relay_demo:
            from door_control import DemoGpioOutputs
            outputs = DemoGpioOutputs(relay_enabled=True, active_high=args.relay_active == "high")
        else:
            outputs = GpioOutputs(relay_enabled=relay_enabled, active_high=args.relay_active == "high")
    speaker = Speaker(enabled=args.hardware and not args.no_audio, simulate=simulate,
                      alsa_device=os.environ.get("SMART_DOOR_ALSA_DEVICE"))
    try:
        if args.enable_unlock and args.no_preview and not speaker.program:
            raise RuntimeError("Install espeak-ng or use a display for the liveness prompts.")
        return DoorController(outputs, speaker, relay_enabled=relay_enabled, unlock_cooldown=args.unlock_cooldown, pulse_seconds=6.5 if args.relay_demo else PULSE_SECONDS)
    except Exception:
        outputs.close()
        speaker.close()
        raise


def run_simulation(args):
    gate = RecognitionGate(frames=args.confirm_frames, leave_seconds=args.leave_seconds,
                           notification_cooldown=args.notification_cooldown)
    controller = controller_for(args, simulate=True)
    resident = Observation("Demo Resident", .85, (20, 80, 90, 100))
    visitor = Observation(None, .11, (150, 80, 90, 100))
    try:
        for _ in range(args.confirm_frames):
            outcome = gate.observe([resident, visitor], monotonic())
        assert outcome.command == "GRANTED"
        assert {event.result for _, event in outcome.events} == {"GRANTED", "DENIED"}
        for _, event in outcome.events:
            print(f"[simulation] {event.result} {event.name}, score {event.score:.3f}, "
                  f"notify={event.notify}", flush=True)
        controller.submit(outcome.command)
        sleep(PULSE_SECONDS + .15)
        assert not gate.observe([resident, visitor], monotonic()).events

        gate.observe([], monotonic())
        sleep(args.leave_seconds + .05)
        for _ in range(args.confirm_frames):
            outcome = gate.observe([visitor], monotonic())
        assert outcome.command == "DENIED"
        print("[simulation] Unknown visitor alone: denial", flush=True)
        controller.submit(outcome.command)
        sleep(PULSE_SECONDS + .15)
    finally:
        controller.close()
    return int(controller.faulted)


def run_bench(args):
    print("Disconnect the solenoid and the 12 V load circuit from the relay contacts.")
    if input("Type DISCONNECTED to run the relay-only test: ").strip() != "DISCONNECTED":
        print("Bench test cancelled.")
        return 1
    controller = controller_for(args, bench=True)
    try:
        print("Starting one five-second relay pulse. Measure continuity at the unloaded contacts.")
        controller.submit("GRANTED")
        sleep(PULSE_SECONDS + .25)
    finally:
        controller.close()
    return int(controller.faulted)


def show_preview(cv2, frame, observations, outcome):
    green, red, amber = (0, 220, 0), (0, 0, 240), (0, 210, 245)
    for i, observation in enumerate(observations):
        x, y, w, h = map(int, observation.box)
        if i in outcome.granted:
            color, label = green, observation.name
        elif i in outcome.unknown:
            color, label = red, "UNKNOWN"
        else:
            color, label = amber, "Verifying"
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        cv2.putText(frame, label, (x, max(18, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, .50, color, 2)
    color = green if outcome.granted else red if outcome.label.startswith("ACCESS DENIED") else amber
    cv2.putText(frame, outcome.label, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, .63, color, 2)
    detail = outcome.prompt
    if not detail and len(observations) == 1:
        detail = f"Similarity: {observations[0].score:.3f}"
    if detail:
        cv2.putText(frame, detail, (12, 54), cv2.FONT_HERSHEY_SIMPLEX, .58, color, 2)
    cv2.imshow("Smart Door Security System", frame)
    return cv2.waitKey(1) & 0xFF in (ord("q"), 27)



def run_camera(args):
    import cv2

    from face_engine import FaceEngine, PassiveLiveness, face_yaw, photo_jpeg

    if args.state_dir is not None:
        args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    engine = FaceEngine(MODELS / "face_detection_yunet_2023mar.onnx",
                        MODELS / "face_recognition_sface_2021dec.onnx", DATABASE, args.threshold)
    pad = PassiveLiveness(args.pad_model, args.pad_threshold) if args.pad_model else None
    gate = RecognitionGate(frames=args.confirm_frames, leave_seconds=args.leave_seconds,
                           notification_cooldown=args.notification_cooldown,
                           liveness_seconds=args.liveness_seconds if pad and not args.passive_only else None,
                           unlock_cooldown=max(args.unlock_cooldown, PULSE_SECONDS))
    cloud = camera = None
    controller = controller_for(args)
    try:
        cloud = open_cloud(args)
        if isinstance(args.camera, str):
            camera = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
        else:
            camera = cv2.VideoCapture(args.camera)
        if not camera.isOpened():
            raise RuntimeError("Camera could not be opened. Check the camera index and whether it is in use.")
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if args.enable_unlock:
            print(f"Relay armed for a confirmed {args.lock_type} installation.")
        print("Camera running. Press Ctrl+C to stop." if args.no_preview else "Camera running. Press Q to stop.")
        spoken_prompt = None
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                raise RuntimeError("Camera stopped returning frames.")
            faces = engine.detect(frame)
            observations = []
            for face in faces:
                name, score = engine.recognize(frame, face)
                observations.append(Observation(name, score, tuple(map(float, face[:4])),
                                                face_yaw(face) if pad else None))
            check = (lambda i: pad.allows(frame, faces[i])) if pad else None
            now = monotonic()
            outcome = gate.observe(observations, now, check, can_grant=controller.ready_to_grant(now))
            if outcome.command:
                controller.submit(outcome.command)
            if outcome.prompt and spoken_prompt != outcome.prompt:
                print(outcome.prompt, flush=True)
                if args.no_preview:
                    controller.speaker.say(outcome.prompt)
            spoken_prompt = outcome.prompt

            for index, decision in outcome.events:
                picture = None
                if args.capture_unknown and decision.result == "DENIED" and index in outcome.unknown:
                    with suppress(cv2.error):
                        picture = photo_jpeg(frame, faces[index])
                lock_command = ("SECURE_REQUESTED"
                                if args.enable_unlock and not controller.faulted and outcome.command == "DENIED"
                                else "UNVERIFIED")
                log_access(decision, cloud, picture=picture,
                           lock_command=lock_command if decision.result == "DENIED" else None,
                           state_dir=args.state_dir)
            if controller.faulted:
                raise RuntimeError("GPIO fault. Check the relay and LED connections before restarting.")
            if not args.no_preview and show_preview(cv2, frame, observations, outcome):
                return 0
    finally:
        controller.close()
        if camera is not None:
            camera.release()
            if not args.no_preview:
                cv2.destroyAllWindows()
        if cloud is not None:
            cloud.close()


def main(argv=None):
    args = settings(argv)
    try:
        if args.setup_writer:
            return setup_windows_writer(state_path(OUTBOX, args.state_dir))
        if args.sync_pending:
            return sync_saved_events(state_path(OUTBOX, args.state_dir))
        if args.simulate:
            return run_simulation(args)
        if args.relay_bench:
            return run_bench(args)
        if args.relay_demo:
            print("Disconnect the solenoid and 12V load.")
            if input("Type DISCONNECTED: ").strip() != "DISCONNECTED":
                return 1
        return run_camera(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as error:
        print(f"Stopped safely. {error}")
        return 1


if __name__ == "__main__":
    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(main())
