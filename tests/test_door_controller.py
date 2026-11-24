import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition
from time import monotonic
from unittest.mock import Mock, patch
from urllib.error import URLError
from wave import open as open_wave
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import recognize_face
import supabase_events
import writer_credentials
from door_control import DOORBELL_PIN, DoorController, Speaker, open_doorbell
from enrollment_auth import require_enrollment_password
from recognition_gate import Observation, RecognitionGate
from supabase_events import EVENTS_RPC, SupabaseEvents


class RecordingOutputs:
    def __init__(self, fail_unlock=False):
        self.condition = Condition()
        self.states = []
        self.fail_unlock = fail_unlock
        self.closed = False

    def apply(self, unlock, green, red):
        if unlock and self.fail_unlock:
            raise RuntimeError("mock relay fault")
        with self.condition:
            self.states.append(((unlock, green, red), monotonic()))
            self.condition.notify_all()

    def close(self):
        self.closed = True

    def after(self, start, target):
        with self.condition:
            found = self.condition.wait_for(
                lambda: any(state == target for state, _ in self.states[start:]), timeout=2
            )
            if not found:
                raise AssertionError(f"State {target} not found in {self.states}")
            return next((index, stamp) for index, (state, stamp) in enumerate(self.states)
                        if index >= start and state == target)


class DoorControllerTests(unittest.TestCase):
    def controller(self, outputs, pulse=.08):
        door = DoorController(outputs, Mock(), relay_enabled=True, unlock_cooldown=.2, pulse_seconds=pulse)
        self.addCleanup(door.close)
        return door

    def test_grant_and_denial_expire_without_camera_frames(self):
        outputs = RecordingOutputs()
        door = self.controller(outputs)
        door.submit("GRANTED")
        index, start = outputs.after(1, (True, True, False))
        secure, end = outputs.after(index + 1, (False, False, False))
        self.assertGreaterEqual(end - start, .07)
        door.submit("DENIED")
        red, start = outputs.after(secure + 1, (False, False, True))
        _, end = outputs.after(red + 1, (False, False, False))
        self.assertGreaterEqual(end - start, .07)
        self.assertEqual(sum(unlock for (unlock, _, _), _ in outputs.states), 1)

    def test_denial_aborts_existing_unlock(self):
        outputs = RecordingOutputs()
        door = self.controller(outputs, pulse=1)
        index = outputs.after(0, (False, False, False))[0]
        door.submit("GRANTED")
        index = outputs.after(index + 1, (True, True, False))[0]
        door.submit("DENIED")
        outputs.after(index + 1, (False, False, True))

    def test_verified_grant_can_replace_red_indicator(self):
        outputs = RecordingOutputs()
        door = self.controller(outputs, pulse=1)
        door.submit("DENIED")
        index = outputs.after(1, (False, False, True))[0]
        self.assertTrue(door.ready_to_grant(monotonic()))
        door.submit("GRANTED")
        outputs.after(index + 1, (True, True, False))

    def test_headless_audio_synthesizes_then_plays_with_alsa(self):
        speaker = Speaker(enabled=False, alsa_device="plughw:CARD=USB,DEV=0")
        speaker.program = "espeak-ng"
        speaker.player = "aplay"
        with patch.object(speaker, "run_audio", return_value=True) as run_audio:
            self.assertTrue(speaker.play("Access Granted. Welcome!"))
        synthesis, playback = [call.args[0] for call in run_audio.call_args_list]
        self.assertEqual(synthesis[:2], ["espeak-ng", "-w"])
        self.assertEqual(synthesis[-1], "Access Granted. Welcome!")
        self.assertEqual(playback[:4], ["aplay", "-q", "-D", "plughw:CARD=USB,DEV=0"])
        self.assertEqual(playback[-1], synthesis[2])

    def test_relay_error_and_shutdown_leave_secure(self):
        outputs = RecordingOutputs(fail_unlock=True)
        door = self.controller(outputs)
        door.submit("GRANTED")
        door.worker.join(timeout=2)
        self.assertTrue(door.faulted)
        self.assertTrue(outputs.closed)
        self.assertEqual(outputs.states[-1][0], (False, False, False))


def gate(**kw):
    return RecognitionGate(frames=3, leave_seconds=1, notification_cooldown=30, **kw)


class RecognitionGateTests(unittest.TestCase):
    face = Observation("Resident", .9, (0, 0, 80, 80), 0)
    second = Observation("Second resident", .8, (100, 0, 80, 80), 0)
    unknown = Observation(None, .12, (200, 0, 80, 80), 0)
    other_unknown = Observation(None, .17, (300, 0, 80, 80), 0)

    def observe(self, state, faces, start):
        for i in range(3):
            outcome = state.observe(faces, start + .01 * i)
        return outcome

    def test_startup_stabilizes_and_continuous_presence_grants_once(self):
        state = gate()
        self.assertFalse(state.observe([self.face], 1).events)
        self.assertFalse(state.observe([self.face], 1.01).events)
        self.assertEqual(state.observe([self.face], 1.02).command, "GRANTED")
        self.assertIsNone(state.observe([self.face], 18).command)
        self.assertFalse(state.observe([self.face], 19).events)

    def test_all_registered_and_mixed_group(self):
        for extras in ([], [self.unknown, self.other_unknown]):
            with self.subTest(extras=extras):
                state = gate()
                group = [self.face, self.second, *extras]
                state.observe(group, 1)
                state.observe(group[::-1], 1.01)
                outcome = state.observe(group, 1.02)
                self.assertEqual(outcome.command, "GRANTED")
                by_index = {i: (event.name, event.result, event.notify) for i, event in outcome.events}
                self.assertEqual(by_index[0], ("Resident", "GRANTED", False))
                self.assertEqual(by_index[1], ("Second resident", "GRANTED", False))
                self.assertEqual(outcome.granted, {0, 1})
                if extras:
                    self.assertEqual(outcome.unknown, {2, 3})
                    self.assertEqual({by_index[i][1] for i in outcome.unknown}, {"DENIED"})
                    self.assertEqual(sum(by_index[i][2] for i in outcome.unknown), 1)
                self.assertFalse(state.observe(group[::-1], 2).events)

    def test_unknown_arriving_during_grant_is_logged_without_relocking(self):
        state = gate()
        self.assertEqual(self.observe(state, [self.face], 1).command, "GRANTED")
        outcome = self.observe(state, [self.face, self.unknown], 2)
        self.assertEqual(outcome.events[0][1].result, "DENIED")
        self.assertIsNone(outcome.command)
        self.assertEqual(state.observe([self.unknown], 3).command, "SECURE")

    def test_unknown_only_and_registered_arrival_without_empty_frame(self):
        state = gate()
        first = self.observe(state, [self.unknown], 1)
        self.assertEqual(first.command, "DENIED")
        self.assertTrue(first.events[0][1].notify)
        self.assertEqual(self.observe(state, [self.unknown, self.face], 2).command, "GRANTED")
        later = self.observe(state, [self.unknown, self.other_unknown], 3)
        self.assertEqual(later.command, "DENIED")
        self.assertFalse(later.events[0][1].notify)

    def test_new_visit_during_cooldown_can_unlock_when_ready(self):
        state = gate()
        self.assertEqual(self.observe(state, [self.face], 1).command, "GRANTED")
        self.assertIsNone(state.observe([], 2).command)
        next_group = self.observe(state, [self.second], 3)
        self.assertEqual(next_group.events[0][1].name, self.second.name)
        self.assertIsNone(next_group.command)
        self.assertIsNone(state.observe([self.second], 10, can_grant=False).command)
        self.assertEqual(state.observe([self.second], 11).command, "GRANTED")
        self.assertIsNone(state.observe([self.second], 20).command)

    def test_duplicate_registered_identity_cannot_grant(self):
        state = gate()
        duplicate = Observation(self.face.name, .91, self.second.box, 0)
        self.assertIsNone(self.observe(state, [self.face, duplicate], 1).command)
        self.assertEqual(state.observe([self.face], 2).command, "GRANTED")

    def test_liveness_is_required_and_checks_the_correct_face(self):
        with patch("recognition_gate.choice", return_value=1):
            state = gate(liveness_seconds=15)
            first = self.observe(state, [self.unknown, self.face], 1)
            self.assertEqual(first.command, "DENIED")
            self.assertIsNotNone(first.prompt)
            state.observe([self.unknown, self.face], 1.5)
            turned = Observation("Resident", .9, self.face.box, .21)
            pad = Mock(return_value=False)
            state.observe([turned, self.unknown], 2, pad)
            failed = state.observe([self.unknown, turned], 2.1, pad)
            pad.assert_called_once_with(1)
            self.assertEqual(failed.events[0][1].result, "DENIED")
            self.assertEqual(failed.command, "DENIED")

            genuine = gate(liveness_seconds=15)
            self.observe(genuine, [self.face, self.unknown], 3)
            genuine.observe([self.face, self.unknown], 3.5)
            pad = Mock(side_effect=lambda index: index == 0)
            for i, sample in enumerate([turned, turned, self.face, self.face,
                                        turned, turned, self.face, self.face, turned, turned]):
                outcome = genuine.observe([sample, self.unknown], 4 + i * .1, pad)
                if i < 9:
                    self.assertNotEqual(outcome.command, "GRANTED")
            self.assertEqual(outcome.command, "GRANTED")
            self.assertEqual(pad.call_count, 3)



class CredentialTests(unittest.TestCase):
    def test_recognition_uses_saved_writer_without_credentials_prompt(self):
        project = "https://test.supabase.co"
        with (patch.dict(os.environ, {}, clear=True),
              patch.object(supabase_events, "project_settings", return_value=(project, "sb_publishable_mock")),
              patch.object(supabase_events, "read_writer", return_value=("writer@example.test", "fixture")),
              patch.object(SupabaseEvents, "verify_writer") as verify,
              patch("builtins.input", side_effect=AssertionError("Recognition prompted")),
              tempfile.TemporaryDirectory() as directory,
              patch.object(recognize_face, "OUTBOX", Path(directory) / "queue.sqlite3")):
            cloud = recognize_face.open_cloud(recognize_face.settings([]))
            try:
                self.assertEqual(cloud.email, "writer@example.test")
                verify.assert_called_once()
            finally:
                cloud.close()

    def test_recognition_without_writer_is_local_only_and_never_prompts(self):
        project = "https://test.supabase.co"
        with (patch.dict(os.environ, {}, clear=True),
              patch.object(supabase_events, "project_settings", return_value=(project, "sb_publishable_mock")),
              patch.object(supabase_events, "read_writer", return_value=("", "")),
              patch("builtins.input", side_effect=AssertionError("Recognition prompted"))):
            self.assertIsNone(recognize_face.open_cloud(recognize_face.settings([])))
            with self.assertRaisesRegex(RuntimeError, "Configure the Supabase writer"):
                recognize_face.open_cloud(recognize_face.settings(["--supabase"]))

    def test_service_uses_systemd_credential_and_private_state_directory(self):
        project = "https://test.supabase.co"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_dir = root / "credential"
            secret_dir.mkdir()
            (secret_dir / "supabase-writer-password").write_text("fixture password\n", encoding="utf-8")
            state_dir = root / "state"
            state_dir.mkdir()
            env = {"CREDENTIALS_DIRECTORY": str(secret_dir), "SUPABASE_DEVICE_EMAIL": "writer@example.test"}
            with (patch.dict(os.environ, env, clear=True),
                  patch.object(supabase_events, "project_settings", return_value=(project, "sb_publishable_mock")),
                  patch.object(SupabaseEvents, "verify_writer", side_effect=AssertionError("Network during startup")),
                  patch.object(SupabaseEvents, "start") as start):
                args = recognize_face.settings(["--offline-first", "--state-dir", str(state_dir),
                                                 "--camera", "/dev/v4l/by-id/usb-camera-video-index0"])
                self.assertEqual(args.camera, "/dev/v4l/by-id/usb-camera-video-index0")
                cloud = recognize_face.open_cloud(args)
                start.assert_called_once()
                self.assertEqual(cloud.password, "fixture password")
                self.assertEqual(cloud.database, state_dir / "door_event_outbox.sqlite3")
                decision = recognize_face.RecognitionGate(frames=1, leave_seconds=1, notification_cooldown=30)
                outcome = decision.observe([Observation(None, .1, (0, 0, 80, 80))], 0)
                recognize_face.log_access(outcome.events[0][1], cloud, state_dir=state_dir)
                self.assertIn("UNKNOWN,DENIED", (state_dir / "access_logs.csv").read_text(encoding="utf-8"))
                with closing(sqlite3.connect(cloud.database)) as connection:
                    self.assertEqual(connection.execute("select count(*) from pending").fetchone()[0], 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows credential encryption")
    def test_windows_writer_round_trip_and_replacement(self):
        project = "https://test.supabase.co"
        secret = "synthetic-test-secret"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "writers" / "example.dpapi"
            with patch.object(writer_credentials, "credential_path", return_value=path):
                self.assertEqual(writer_credentials.read_writer(project), ("", ""))
                writer_credentials.save_writer(project, "writer@example.test", secret)
                self.assertNotIn(secret.encode(), path.read_bytes())
                self.assertEqual(writer_credentials.read_writer(project), ("writer@example.test", secret))
                writer_credentials.save_writer(project, "writer@example.test", "updated-credential")
                self.assertEqual(writer_credentials.read_writer(project), ("writer@example.test", "updated-credential"))

    def test_enrollment_password_is_created_and_verified(self):
        password = "local-test-passphrase"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset" / ".enrollment-auth.json"
            with patch("enrollment_auth.getpass", side_effect=[password, password]):
                self.assertTrue(require_enrollment_password(path))
            self.assertNotIn(password, path.read_text(encoding="utf-8"))
            with patch("enrollment_auth.getpass", return_value="incorrect"):
                self.assertFalse(require_enrollment_password(path))
            with patch("enrollment_auth.getpass", return_value=password):
                self.assertTrue(require_enrollment_password(path))



class DisplayDoorbellAndEnrollmentTests(unittest.TestCase):
    def test_oled_shows_entire_frame_with_no_status_overlay(self):
        import numpy as np
        from display_panel import render_oled_frame

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:60, :80] = 255
        frame[-60:, -80:] = 255
        for resolution, height, view_width in (("128x64", 64, 85), ("128x32", 32, 43)):
            with self.subTest(resolution=resolution):
                pixels = render_oled_frame(frame, resolution)
                left = (128 - view_width) // 2
                self.assertEqual(pixels.shape, (height, 128))
                self.assertEqual(set(np.unique(pixels)), {0, 255})
                self.assertEqual(pixels[0, left], 255)
                self.assertEqual(pixels[-1, left + view_width - 1], 255)
                self.assertFalse(pixels[:, :left].any())
                self.assertFalse(pixels[:, left + view_width:].any())
                self.assertFalse(render_oled_frame(np.zeros_like(frame), resolution).any())

    def test_oled_throttles_and_copies_camera_frames_before_annotations(self):
        import numpy as np
        from display_panel import PanelOutput

        with (patch("display_panel.Thread"),
              patch("display_panel.monotonic", side_effect=[0, .1, .25])):
            panel = PanelOutput("128x64", 0x3c)
            frame = np.zeros((32, 48, 3), dtype=np.uint8)
            panel.observe(frame)
            first = panel.latest[0]
            frame[:] = 255
            panel.observe(frame)
            self.assertIs(panel.latest[0], first)
            self.assertFalse(first.any())
            panel.observe(frame)
            self.assertTrue(panel.latest[0].all())
            panel.close()

    def test_oled_blanks_stale_feed_and_cleans_up_i2c(self):
        import numpy as np
        from display_panel import PanelOutput
        from types import SimpleNamespace

        screen = Mock()
        serial = Mock()
        image = Mock()
        oled = Mock(return_value=screen)
        i2c = Mock(return_value=serial)
        modules = {
            "luma.core.interface.serial": SimpleNamespace(i2c=i2c),
            "luma.oled.device": SimpleNamespace(ssd1306=oled),
            "PIL": SimpleNamespace(Image=image),
        }
        with (patch.dict(sys.modules, modules), patch("display_panel.Thread"),
              patch("display_panel.monotonic", side_effect=[10, 10, 12])):
            panel = PanelOutput("128x32", 0x3d)
            panel.observe(np.full((48, 64, 3), 255, dtype=np.uint8))

            def rendered(_image):
                if screen.display.call_count == 2:
                    panel.stop.set()

            screen.display.side_effect = rendered
            panel.run()
        i2c.assert_called_once_with(port=1, address=0x3d)
        oled.assert_called_once_with(serial, width=128, height=32)
        first, second = [call.args[0] for call in image.fromarray.call_args_list]
        self.assertEqual(first.shape, (32, 128))
        self.assertTrue(first.any())
        self.assertFalse(second.any())
        screen.cleanup.assert_called_once()

    def test_windows_oled_preview_renders_live_feed_without_recognition(self):
        import cv2
        import numpy as np

        camera = Mock()
        camera.read.return_value = True, np.full((48, 64, 3), 255, dtype=np.uint8)
        with (patch.object(cv2, "VideoCapture", return_value=camera) as source,
              patch.object(cv2, "imshow") as show, patch.object(cv2, "waitKey", return_value=ord("q")),
              patch.object(cv2, "destroyAllWindows"), patch.object(recognize_face, "open_cloud") as cloud):
            result = recognize_face.main(["--simulate-display", "--display-layout", "mono32", "--camera", "1"])
        self.assertEqual(result, 0)
        self.assertEqual(show.call_args.args[1].shape, (128, 512))
        source.assert_called_once_with(1)
        cloud.assert_not_called()
        camera.release.assert_called_once()


    def test_doorbell_button_calls_audio_only(self):
        from types import SimpleNamespace

        button = Mock()
        factory = Mock(return_value=button)
        speaker = Mock()
        with patch.dict(sys.modules, {"gpiozero": SimpleNamespace(Button=factory)}):
            self.assertIs(open_doorbell(speaker), button)
        factory.assert_called_once_with(DOORBELL_PIN, pull_up=True, bounce_time=.10)
        button.when_pressed()
        self.assertEqual(speaker.method_calls, [unittest.mock.call.ring()])

    def test_doorbell_chime_is_valid_pcm(self):
        speaker = Speaker(enabled=False, alsa_device="default")
        speaker.player = "aplay"

        def read_wav(command):
            self.assertEqual(command[:4], ["aplay", "-q", "-D", "default"])
            with open_wave(command[-1], "rb") as file:
                self.assertEqual(file.getnchannels(), 1)
                self.assertEqual(file.getsampwidth(), 2)
                self.assertEqual(file.getnframes(), 8820)
                self.assertTrue(any(file.readframes(500)))
            return True

        with patch.object(speaker, "run_audio", side_effect=read_wav):
            self.assertTrue(speaker.play_bell())

    def test_failed_enrollment_write_preserves_existing_profiles(self):
        from face_engine import save_enrollments

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authorized_faces.json"
            original = {"users": [{"name": "Demo", "embeddings": [[0.125]]}]}
            save_enrollments(path, original)
            with self.assertRaises(ValueError):
                save_enrollments(path, {"users": [float("nan")]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_camera_disconnect_releases_camera_and_stops_controller(self):
        import cv2

        camera = Mock()
        camera.read.return_value = False, None
        door = Mock()
        with (patch.object(cv2, "VideoCapture", return_value=camera),
              patch("face_engine.FaceEngine"),
              patch.object(recognize_face, "controller_for", return_value=door)):
            result = recognize_face.main(["--no-preview", "--local-only"])
        self.assertEqual(result, 1)
        door.close.assert_called_once()
        camera.release.assert_called_once()



class SupabaseQueueTests(unittest.TestCase):
    def test_legacy_events_survive_and_denial_precedes_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "old.sqlite3"
            project = "https://test.supabase.co"
            email = "writer@example.test"
            writer_id = str(uuid4())
            legacy_event = dict(id=str(uuid4()), occurred_at="2026-11-23T00:00:00Z",
                                person="Prior record", result="GRANTED", similarity=.9)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("""create table pending (
                    id integer primary key autoincrement, project text not null,
                    account text not null, payload text not null)""")
                connection.execute("insert into pending(project,account,payload) values(?,?,?)",
                                   (project, email, json.dumps(legacy_event)))
            client = SupabaseEvents(database, project, "sb_publishable_mock", email, "mock", background=False)
            event_id = client.enqueue(datetime.now(timezone.utc), "UNKNOWN", "DENIED", .1,
                                      notify=True, lock_command="SECURE_REQUESTED", photo=b"jpeg")
            calls = []
            fail_storage = True

            def request(route, payload, token=None):
                calls.append((route, payload))
                if route.startswith("/auth/"):
                    return json.dumps({"access_token": "mock", "expires_in": 3600,
                                       "user": {"id": writer_id}}).encode()
                if route.startswith("/storage/") and fail_storage:
                    raise URLError("mock offline")
                return b""

            with patch.object(client, "request", request):
                self.assertEqual(client.flush_pending(), 2)
                self.assertEqual(calls[1][0], EVENTS_RPC)
                self.assertEqual(calls[1][1]["events"][0], legacy_event)
                self.assertTrue(calls[1][1]["events"][1]["notify"])
                self.assertNotIn("photo", calls[1][1]["events"][1])
                with self.assertRaises(URLError):
                    client.flush_pending()
                fail_storage = False
                self.assertEqual(client.flush_pending(), 1)
                self.assertIn(f"{writer_id}/{event_id}.jpg", calls[-2][0])
                self.assertEqual(calls[-1][1], {"event_id": event_id})
                self.assertEqual(client.flush_pending(), 0)


if __name__ == "__main__":
    unittest.main()
