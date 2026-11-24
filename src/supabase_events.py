"""Queue access events locally and upload them from the camera process."""

import json
import os
import re
import sqlite3
import warnings
from contextlib import closing
from getpass import GetPassWarning, getpass
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from writer_credentials import read_writer, save_writer


PASSWORD_SETTING = "SUPABASE_DEVICE_PASSWORD"
LOCAL_CONFIG = Path(__file__).resolve().parent.parent / "dashboard.local.json"
REQUEST_TIMEOUT = 8
EVENTS_RPC = "/rest/v1/rpc/record_door_events"


def load_local_supabase_settings():
    settings = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
    project = settings["project_url"].strip().rstrip("/")
    key = settings["publishable_key"].strip()
    if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", project):
        raise ValueError("Use an HTTPS Supabase project URL in dashboard.local.json.")
    if not key.startswith("sb_publishable_"):
        raise ValueError("Use a Supabase publishable key in dashboard.local.json.")
    return project, key


def project_settings():
    project = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if LOCAL_CONFIG.is_file() and (not project or not key):
        saved_project, saved_key = load_local_supabase_settings()
        project = project or saved_project
        if project == saved_project:
            key = key or saved_key
    return project, key


def configured_writer_password():
    password = os.environ.get(PASSWORD_SETTING, "")
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if password or not directory:
        return password
    try:
        return (Path(directory) / "supabase-writer-password").read_text(encoding="utf-8").removesuffix("\n")
    except FileNotFoundError:
        return ""


def setup_windows_writer(database):
    if os.name != "nt":
        print("Use SUPABASE_DEVICE_EMAIL and SUPABASE_DEVICE_PASSWORD on Raspberry Pi or Linux.")
        return 1
    try:
        project, key = project_settings()
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", project) or not key.startswith("sb_publishable_"):
            print("Set the HTTPS Supabase project URL and publishable key in dashboard.local.json or the environment.")
            return 1
        email = input("PC writer email: ").strip()
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("PC writer password: ")
        if not email or not password:
            print("Both writer credentials are required.")
            return 1
        client = SupabaseEvents(database, project, key, email.lower(), password, background=False)
        client.verify_writer()
        save_writer(project, client.email, password)
        print("Verified and saved the Supabase writer for this Windows account.")
    except HTTPError as error:
        report_supabase_error(error)
        return 1
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print("\nOpen an interactive terminal to set up the writer.")
        return 1
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
        print("Could not verify or save the writer. Check the project settings and connection.")
        return 1
    return 0



def report_supabase_error(error):
    with error:
        try:
            body = json.loads(error.read(16_384))
        except (OSError, ValueError):
            body = {}
    if not isinstance(body, dict):
        body = {}

    if "/auth/v1/" in error.url:
        print(f"PC writer sign-in failed (HTTP {error.code}).")
        code = body.get("error_code") or body.get("code")
        if code == "email_not_confirmed":
            print("Confirm the PC writer email in Supabase Authentication.")
        else:
            print("Check the PC writer email and password.")
        return

    print(f"Supabase rejected the upload (HTTP {error.code}).")
    message = body.get("message")
    if message == "This account cannot submit door events":
        print("The PC writer UID must be listed under writer_id in public.door_devices.")
    elif message == "permission denied for function record_door_events":
        print("The authenticated role needs EXECUTE permission on public.record_door_events(jsonb).")
    else:
        print("Check the Data API and the PC writer pairing in public.door_devices.")


def sync_saved_events(database):
    if not database.is_file():
        print("There is no Supabase queue on this PC yet.")
        return 0
    try:
        client = SupabaseEvents.from_environment(database, background=False)
        if client is None:
            return 1
        count = 0
        while uploaded := client.flush_pending():
            count += uploaded
        if count:
            print(f"Supabase confirmed upload of {count} event(s). Refresh the dashboard.")
        else:
            print("No pending events for this Supabase project and PC writer.")
        with closing(sqlite3.connect(database)) as connection:
            remaining = connection.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        if remaining:
            print(f"{remaining} event(s) remain queued. Use the project and PC writer that recorded them.")
            return 1
    except HTTPError as error:
        report_supabase_error(error)
        print("Pending events are safe on this PC. Run --sync-pending again after fixing the error.")
        return 1
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
        print("Could not sync the saved events. Check the Supabase settings, local queue, and internet connection.")
        return 1
    return 0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SupabaseEvents:
    @classmethod
    def from_environment(cls, database, *, background=True):
        url, key = project_settings()
        if not url and not key:
            print("Supabase sync is off. Saving access events to CSV.")
            return None
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", url) or not key.startswith("sb_publishable_"):
            print("Supabase sync disabled. Use the HTTPS project URL and a Supabase publishable key.")
            return None

        email = os.environ.get("SUPABASE_DEVICE_EMAIL", "").strip()
        password = configured_writer_password()
        if not email and not password:
            try:
                email, password = read_writer(url)
            except (OSError, ValueError):
                print("Could not read saved Supabase credentials. Run --setup-writer again.")
                return None
        if not email or not password:
            help_text = "Run --setup-writer once." if os.name == "nt" else "Set the writer environment variables."
            print(f"Supabase writer is not configured. {help_text}")
            return None
        return cls(database, url, key, email.strip().lower(), password, background=background)

    def __init__(self, database, url, key, email, password, *, background=True):
        self.database = database
        self.url = url
        self.key = key
        self.email = email
        self.password = password
        self.opener = build_opener(NoRedirect())
        self.token = None
        self.writer_id = None
        self.token_expiry = 0
        self.stop = Event()
        self.wake = Event()

        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS pending (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      project TEXT NOT NULL,
                      account TEXT NOT NULL,
                      payload TEXT NOT NULL
                   )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(pending)")}
            if "photo" not in columns:
                connection.execute("ALTER TABLE pending ADD COLUMN photo BLOB")
            if "event_uploaded" not in columns:
                connection.execute("ALTER TABLE pending ADD COLUMN event_uploaded INTEGER NOT NULL DEFAULT 0")
        self.worker = None
        if background:
            self.start()

    def start(self):
        if self.worker is None:
            self.worker = Thread(target=self.sync, name="supabase-events", daemon=True)
            self.worker.start()

    def enqueue(self, timestamp, name, result, similarity, *, notify=False, lock_command=None, photo=None):
        event_id = str(uuid4())
        payload = json.dumps(
            {
                "id": event_id,
                "occurred_at": timestamp.isoformat(),
                "person": name,
                "result": result,
                "similarity": similarity,
                "notify": notify and result == "DENIED",
                "lock_command": lock_command,
            },
            allow_nan=False,
        )
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO pending (project, account, payload, photo) VALUES (?, ?, ?, ?)",
                (self.url, self.email, payload, photo if result == "DENIED" else None),
            )
        self.wake.set()
        return event_id

    def request(self, route, payload, token=None):
        headers = {"apikey": self.key}
        if isinstance(payload, bytes):
            headers.update({"Content-Type": "image/jpeg", "x-upsert": "true"})
            body = payload
        else:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            self.url + route,
            data=body,
            headers=headers,
            method="POST",
        )
        with self.opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            return response.read()

    def authenticate(self):
        if self.token is None or monotonic() >= self.token_expiry:
            session = json.loads(
                self.request(
                    "/auth/v1/token?grant_type=password",
                    {"email": self.email, "password": self.password},
                )
            )
            self.token = session["access_token"]
            self.writer_id = session.get("user", {}).get("id")
            self.token_expiry = monotonic() + max(0, session["expires_in"] - 30)

    def write_events(self, events):
        self.authenticate()
        try:
            self.request(EVENTS_RPC, {"events": events}, self.token)
        except HTTPError as exc:
            if exc.code == 401:
                self.token = None
            raise

    def verify_writer(self):
        # The RPC checks writer permission before validating the batch size.
        # An empty batch checks the current writer without creating an event.
        try:
            self.write_events([])
        except HTTPError as error:
            if error.code != 400 or not error.url.endswith(EVENTS_RPC):
                raise
            with error:
                result = json.loads(error.read(16_384))
            if not isinstance(result, dict) or result.get("code") != "22023":
                raise ValueError("Supabase could not validate the writer account.") from error

    def flush_pending(self):
        with closing(sqlite3.connect(self.database)) as connection:
            rows = connection.execute(
                """SELECT id, payload, photo IS NOT NULL FROM pending
                   WHERE project = ? AND account = ? AND event_uploaded = 0 ORDER BY id LIMIT 50""",
                (self.url, self.email),
            ).fetchall()
            if rows:
                self.write_events([json.loads(payload) for _, payload, _ in rows])
                with connection:
                    for row_id, _, has_photo in rows:
                        if has_photo:
                            connection.execute("UPDATE pending SET event_uploaded = 1 WHERE id = ?", (row_id,))
                        else:
                            connection.execute("DELETE FROM pending WHERE id = ?", (row_id,))
                return len(rows)

            row = connection.execute(
                """SELECT id, payload, photo FROM pending
                   WHERE project = ? AND account = ? AND event_uploaded = 1 ORDER BY id LIMIT 1""",
                (self.url, self.email),
            ).fetchone()
            if row is None:
                return 0
            row_id, payload, photo = row
            event_id = str(UUID(json.loads(payload)["id"]))
            self.authenticate()
            if not self.writer_id:
                raise ValueError("Supabase did not return the writer ID.")
            object_name = f"{UUID(self.writer_id)}/{event_id}.jpg"
            self.request(f"/storage/v1/object/door-visitor-images/{object_name}", photo, self.token)
            self.request("/rest/v1/rpc/attach_door_event_photo", {"event_id": event_id}, self.token)
            with connection:
                connection.execute("DELETE FROM pending WHERE id = ?", (row_id,))
            return 1

    def sync(self):
        while True:
            self.wake.clear()
            stopping = self.stop.is_set()
            try:
                uploaded = self.flush_pending()
            except HTTPError as error:
                report_supabase_error(error)
                print("Events are queued on this PC.", flush=True)
            except (OSError, ValueError, KeyError, sqlite3.Error):
                print("Supabase sync unavailable. Events are queued on this PC.", flush=True)
            else:
                if uploaded:
                    print(f"Supabase confirmed upload of {uploaded} event(s).", flush=True)
                elif stopping:
                    return
                else:
                    self.wake.wait()
                continue

            if self.stop.wait(30):
                return

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.worker is not None:
            self.worker.join(timeout=2 * REQUEST_TIMEOUT + 2)
            if self.worker.is_alive():
                print("Supabase is still responding. Any unconfirmed events remain queued. Use --sync-pending to retry.")
