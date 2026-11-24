"""Stabilize recognition decisions and apply an optional active liveness gate."""

from collections import Counter
from dataclasses import dataclass
from secrets import choice

UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Decision:
    name: str
    result: str
    score: float
    notify: bool = False


@dataclass(frozen=True)
class Observation:
    name: str | None
    score: float
    box: tuple[float, float, float, float]
    yaw: float | None = None


@dataclass(frozen=True)
class Outcome:
    label: str
    events: tuple[tuple[int, Decision], ...] = ()
    prompt: str | None = None
    command: str | None = None
    granted: frozenset[int] = frozenset()
    unknown: frozenset[int] = frozenset()


@dataclass(eq=False)
class FaceTrack:
    box: tuple[float, float, float, float]
    seen: float
    frame: int
    name: str | None
    count: int = 1
    verified_name: str | None = None
    denied_logged: bool = False
    retry_at: float = float("-inf")


def overlap(first, second):
    x, y, w, h = first
    a, b, c, d = second
    intersection = max(0, min(x + w, a + c) - max(x, a)) * max(0, min(y + h, b + d) - max(y, b))
    union = w * h + c * d - intersection
    return intersection / union if union > 0 else 0



class LivenessChallenge:
    PROMPTS = {
        0: "Look straight at the camera.",
        1: "Turn your head left.",
        -1: "Turn your head right.",
    }

    def __init__(self, now, timeout):
        self.steps = (0, choice((-1, 1)), 0, choice((-1, 1)), 0, choice((-1, 1)))
        self.expires = now + timeout
        self.index = self.count = 0

    @property
    def prompt(self):
        return self.PROMPTS[self.steps[self.index]]

    def advance(self, yaw, passive_check):
        target = self.steps[self.index]
        reached = yaw is not None and (abs(yaw) <= .10 if target == 0 else target * yaw >= .18)
        self.count = self.count + 1 if reached else 0
        if self.count < 2:
            return "WAIT"
        if target != 0 and not passive_check():
            return "FAILED"
        self.count = 0
        self.index += 1
        return "PASSED" if self.index == len(self.steps) else "WAIT"


class RecognitionGate:
    """Track visits independently and choose one hardware action per frame."""

    def __init__(self, *, frames, leave_seconds, notification_cooldown,
                 liveness_seconds=None, unlock_cooldown=8):
        self.frames = frames
        self.leave_seconds = leave_seconds
        self.notification_cooldown = notification_cooldown
        self.liveness_seconds = liveness_seconds
        self.unlock_cooldown = unlock_cooldown
        self.tracks = []
        self.frame = 0
        self.challenge = None
        self.challenge_track = None
        self.challenge_name = None
        self.last_notification = float("-inf")
        self.last_grant = float("-inf")
        self.grant_present = False
        self.grant_pending = False

    def match(self, observations, now):
        self.frame += 1
        self.tracks = [track for track in self.tracks if now - track.seen < self.leave_seconds
                       or track.frame == self.frame - 1]
        pairs = sorted(
            ((overlap(observation.box, track.box), i, j)
             for i, observation in enumerate(observations) for j, track in enumerate(self.tracks)),
            reverse=True,
        )
        matched = {}
        used = set()
        for score, i, j in pairs:
            if score < .25:
                break
            if i not in matched and j not in used:
                matched[i] = self.tracks[j]
                used.add(j)
        for i, observation in enumerate(observations):
            track = matched.get(i)
            if track is None:
                track = FaceTrack(observation.box, now, self.frame, observation.name)
                self.tracks.append(track)
                matched[i] = track
                continue
            consecutive = track.frame == self.frame - 1 and track.name == observation.name
            track.count = track.count + 1 if consecutive else 1
            track.box, track.seen, track.frame, track.name = observation.box, now, self.frame, observation.name
        return matched

    def deny(self, track, score, now):
        if track.denied_logged:
            return None
        track.denied_logged = True
        notify = now - self.last_notification >= self.notification_cooldown
        if notify:
            self.last_notification = now
        return Decision(UNKNOWN, "DENIED", score, notify)

    def observe(self, observations, now, passive_check=None, *, can_grant=True):
        matched = self.match(observations, now)
        events = []
        unknown = set()
        names = Counter(observation.name for observation in observations)
        candidates = {}
        for i, track in matched.items():
            if track.count < self.frames:
                continue
            if track.name is None:
                unknown.add(i)
                denial = self.deny(track, observations[i].score, now)
                if denial:
                    events.append((i, denial))
            elif names[track.name] == 1 and track.verified_name != track.name and now >= track.retry_at:
                candidates[track] = i

        prompt = None
        if self.liveness_seconds is None:
            verified = candidates.values()
        else:
            verified = ()
            if self.challenge_track not in candidates or self.challenge_track.name != self.challenge_name:
                self.challenge = self.challenge_track = self.challenge_name = None
            if self.challenge is None and candidates:
                # One prompt at a time, directed at the largest eligible face.
                self.challenge_track = max(candidates, key=lambda track: track.box[2] * track.box[3])
                self.challenge_name = self.challenge_track.name
                self.challenge = LivenessChallenge(now, self.liveness_seconds)
            if self.challenge is not None:
                track = self.challenge_track
                i = candidates[track]
                status = ("FAILED" if now >= self.challenge.expires else
                          self.challenge.advance(observations[i].yaw, lambda: bool(passive_check and passive_check(i))))
                if status == "PASSED":
                    verified = (i,)
                elif status == "FAILED":
                    denial = self.deny(track, observations[i].score, now)
                    if denial:
                        events.append((i, denial))
                    track.retry_at = now + self.unlock_cooldown
                else:
                    prompt = f"{track.name}: {self.challenge.prompt}"
                if status != "WAIT":
                    self.challenge = self.challenge_track = self.challenge_name = None

        for i in verified:
            track = matched[i]
            track.verified_name = track.name
            events.append((i, Decision(track.name, "GRANTED", observations[i].score)))

        granted = frozenset(i for i, track in matched.items()
                            if track.name is not None and track.name == track.verified_name
                            and names[track.name] == 1)
        command = None
        if granted:
            if not self.grant_present and any(event.result == "GRANTED" for _, event in events):
                self.grant_pending = True
            if self.grant_pending and can_grant and now - self.last_grant >= self.unlock_cooldown:
                command = "GRANTED"
                self.last_grant = now
                self.grant_pending = False
        else:
            self.grant_pending = False
            if any(event.result == "DENIED" for _, event in events):
                command = "DENIED"
            elif self.grant_present and observations:
                command = "SECURE"
        self.grant_present = bool(granted)

        if granted:
            label = "ACCESS GRANTED"
            if len(observations) == 1:
                label += f": {observations[0].name}"
        elif unknown or any(event.result == "DENIED" for _, event in events):
            label = "ACCESS DENIED: UNKNOWN PERSON" if unknown else "ACCESS DENIED: LIVENESS"
        else:
            label = "Verifying faces..." if observations else "Waiting for a face"
        return Outcome(label, tuple(events), prompt, command, granted, frozenset(unknown))
