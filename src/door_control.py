"""Time-bound GPIO and speech. GPIO imports are deferred until Pi mode."""

from contextlib import suppress
from math import pi, sin
from struct import pack
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, Popen, TimeoutExpired
from tempfile import TemporaryDirectory
from threading import Condition, Event, Thread
from time import monotonic
from wave import open as open_wave

GREEN_PIN = 17
RED_PIN = 27
RELAY_PIN = 23
DOORBELL_PIN = 22
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


class Speaker:
    MESSAGES = {
        "GRANTED": "Access Granted. Welcome!",
        "DENIED": "Access Denied. Unauthorized Person Detected!",
    }

    def __init__(self, *, enabled, simulate=False, alsa_device=None, doorbell=False):
        self.alsa_device = alsa_device or ("default" if doorbell else None)
        self.player = which("aplay") if enabled and self.alsa_device else None
        self.program = which("espeak-ng") if enabled and (not self.alsa_device or self.player) else None
        self.simulate = simulate
        self.condition = Condition()
        self.stop = Event()
        self.pending = None
        self.bell_pending = False
        self.last_bell = float("-inf")
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

    def ring(self):
        if self.worker is None or not (self.player or self.simulate):
            return
        with self.condition:
            now = monotonic()
            if not self.stop.is_set() and now - self.last_bell >= 2:
                self.last_bell = now
                self.bell_pending = True
                self.condition.notify()

    def play_bell(self):
        rate = 22050
        samples = []
        for frequency in (784, 587):
            length = rate // 5
            for i in range(length):
                envelope = min(i / 240, (length - i) / 480, 1)
                samples.append(round(9000 * envelope * sin(2 * pi * frequency * i / rate)))
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "doorbell.wav")
            with open_wave(path, "wb") as sound:
                sound.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                sound.writeframes(pack(f"<{len(samples)}h", *samples))
            return self.run_audio([self.player, "-q", "-D", self.alsa_device, path])

    def run(self):
        while not self.stop.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.bell_pending or self.stop.is_set())
                if self.stop.is_set():
                    break
                message = self.pending
                self.pending = None
                if message is None:
                    self.bell_pending = False
            if self.simulate:
                print(f"[simulation] speaker: {message or 'doorbell chime'}", flush=True)
                continue
            try:
                played = self.play(message) if message is not None else self.play_bell()
                if not played and not self.stop.is_set():
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


def open_doorbell(speaker):
    from gpiozero import Button

    if not speaker.player or not speaker.program:
        raise RuntimeError("Install espeak-ng and alsa-utils before enabling the doorbell.")
    button = Button(DOORBELL_PIN, pull_up=True, bounce_time=.10)
    try:
        button.when_pressed = speaker.ring
    except Exception:
        button.close()
        raise
    return button


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
