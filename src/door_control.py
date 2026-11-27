"""Time-bound GPIO and speech. GPIO imports are deferred until Pi mode."""

from contextlib import suppress
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, Popen, TimeoutExpired
from tempfile import TemporaryDirectory
from threading import Condition, Event, Thread
from time import monotonic

GREEN_PIN = 17
RED_PIN = 27
RELAY_PIN = 23
PULSE_SECONDS = 5.0


class SimulatedOutputs:
    def __init__(self, *, verbose=False):
        self.verbose = verbose

    def apply(self, unlock, green, red):
        if self.verbose:
            print(f"[simulation] relay={'UNLOCK' if unlock else 'SECURE'} "
                  f"green={'ON' if green else 'OFF'} red={'ON' if red else 'OFF'}", flush=True)

    def close(self):
        pass


class GpioOutputs:
    def __init__(self, *, relay_enabled, active_high):
        from gpiozero import LED, OutputDevice

        self.relay = self.green = self.red = None
        try:
            if relay_enabled:
                self.relay = OutputDevice(RELAY_PIN, active_high=active_high, initial_value=False)
            self.green = LED(GREEN_PIN, initial_value=False)
            self.red = LED(RED_PIN, initial_value=False)
        except Exception:
            self.close()
            raise

    def apply(self, unlock, green, red):
        if self.relay is not None and not unlock:
            self.relay.off()
        self.green.value = green
        self.red.value = red
        if self.relay is not None and unlock:
            self.relay.on()

    def close(self):
        for output in (self.relay, self.green, self.red):
            if output is not None:
                with suppress(Exception):
                    output.off()
                with suppress(Exception):
                    output.close()



class DemoGpioOutputs(GpioOutputs):
    def __init__(self, **kwargs):
        self.demo_stop = Event()
        self.demo_worker = None
        super().__init__(**kwargs)

    def apply(self, unlock, green, red):
        self.demo_stop.set()
        if self.demo_worker is not None:
            self.demo_worker.join()
            self.demo_worker = None

        super().apply(False, green, red)

        if unlock and green and self.relay is not None:
            self.demo_stop.clear()
            self.demo_worker = Thread(
                target=self.demo_pulse, daemon=True
            )
            self.demo_worker.start()

    def demo_pulse(self):
        try:
            if self.demo_stop.wait(0.5):
                return
            self.relay.on()
            if self.demo_stop.wait(0.1):
                return
            self.green.off()
            self.demo_stop.wait(5.9)
        finally:
            self.relay.off()
            self.green.off()

    def close(self):
        self.demo_stop.set()
        if self.demo_worker is not None:
            self.demo_worker.join()
        super().close()


class Speaker:
    MESSAGES = {
        "GRANTED": "Access Granted. Welcome!",
        "DENIED": "Access Denied. Unauthorized Person Detected!",
    }

    def __init__(self, *, enabled, simulate=False, alsa_device=None):
        self.alsa_device = alsa_device
        self.player = which("aplay") if enabled and alsa_device else None
        self.program = which("espeak-ng") if enabled and (not alsa_device or self.player) else None
        self.simulate = simulate
        self.condition = Condition()
        self.stop = Event()
        self.pending = None
        self.worker = None
        if enabled and not self.program:
            print("Speaker disabled. Install espeak-ng and alsa-utils, then configure the audio output.")
        if self.program or simulate:
            self.worker = Thread(target=self.run, name="door-speaker", daemon=True)
            self.worker.start()

    def announce(self, result):
        self.say(self.MESSAGES[result])

    def say(self, message):
        if self.worker is not None:
            with self.condition:
                self.pending = message
                self.condition.notify()

    def run(self):
        while not self.stop.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.stop.is_set())
                if self.stop.is_set():
                    break
                message = self.pending
                self.pending = None
            if self.simulate:
                print(f"[simulation] speaker: {message}", flush=True)
                continue
            try:
                if not self.play(message) and not self.stop.is_set():
                    print("Could not play the door announcement.", flush=True)
            except OSError:
                print("Could not play the door announcement.", flush=True)

    def play(self, message):
        if not self.alsa_device:
            return self.run_audio([self.program, message])
        with TemporaryDirectory() as directory:
            wave = str(Path(directory) / "announcement.wav")
            if not self.run_audio([self.program, "-w", wave, "--", message]) or self.stop.is_set():
                return False
            return self.run_audio([self.player, "-q", "-D", self.alsa_device, wave])

    def run_audio(self, command):
        with Popen(command, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL) as process:
            deadline = monotonic() + 12
            while process.poll() is None:
                if self.stop.wait(0.1) or monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except TimeoutExpired:
                        process.kill()
                    return False
            return process.returncode == 0

    def close(self):
        with self.condition:
            self.stop.set()
            self.condition.notify_all()
        if self.worker is not None:
            self.worker.join(timeout=2)


class DoorController:
    def __init__(self, outputs, speaker, *, relay_enabled, unlock_cooldown, pulse_seconds=PULSE_SECONDS):
        self.outputs = outputs
        self.speaker = speaker
        self.relay_enabled = relay_enabled
        self.unlock_cooldown = unlock_cooldown
        self.pulse_seconds = pulse_seconds
        self.condition = Condition()
        self.pending = None
        self.stopping = False
        self.faulted = False
        self.last_unlock = float("-inf")
        self.outputs.apply(False, False, False)
        self.worker = Thread(target=self.run, name="door-gpio", daemon=True)
        self.worker.start()

    def ready_to_grant(self, now):
        with self.condition:
            interval = max(self.unlock_cooldown, self.pulse_seconds)
            return (not self.stopping and not self.faulted and self.pending is None
                    and now - self.last_unlock >= interval)

    def submit(self, command):
        with self.condition:
            if self.stopping or self.faulted:
                return
            # Fail closed if a secure/deny arrives before an unlock is processed.
            if command == "GRANTED" and self.pending in ("DENIED", "SECURE"):
                return
            # A continuing unsafe image must not erase an already queued denial.
            if command == "SECURE" and self.pending == "DENIED":
                return
            self.pending = command
            self.condition.notify()

    def run(self):
        deadline = None
        light = None
        try:
            while True:
                with self.condition:
                    while not self.stopping and self.pending is None:
                        remaining = None if deadline is None else deadline - monotonic()
                        if remaining is not None and remaining <= 0:
                            break
                        self.condition.wait(timeout=remaining)
                    if self.stopping:
                        break
                    command, self.pending = self.pending, None
                now = monotonic()
                if deadline is not None and now >= deadline:
                    self.outputs.apply(False, False, False)
                    deadline = light = None
                if command == "SECURE" and light == "green":
                    self.outputs.apply(False, False, False)
                    deadline = light = None
                elif command == "DENIED":
                    self.outputs.apply(False, False, True)
                    light, deadline = "red", monotonic() + self.pulse_seconds
                    self.speaker.announce(command)
                elif command == "GRANTED" and light != "green" and now - self.last_unlock >= self.unlock_cooldown:
                    self.outputs.apply(self.relay_enabled, True, False)
                    with self.condition:
                        self.last_unlock = monotonic()
                    light, deadline = "green", self.last_unlock + self.pulse_seconds
                    self.speaker.announce(command)
        except Exception as error:
            self.faulted = True
            print(f"GPIO fault. Automatic unlock disabled until restart ({type(error).__name__}).", flush=True)
        finally:
            with suppress(Exception):
                self.outputs.apply(False, False, False)
            self.outputs.close()

    def close(self):
        with self.condition:
            self.stopping = True
            self.pending = None
            self.condition.notify()
        self.worker.join(timeout=2)
        if self.worker.is_alive():
            print("GPIO worker did not stop. Isolate the lock circuit and check the hardware.", flush=True)
        self.speaker.close()
