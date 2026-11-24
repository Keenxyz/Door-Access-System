"""Send one synthetic event through the Supabase writer without opening the camera."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

from supabase_events import SupabaseEvents, report_supabase_error

TEST_LABEL = "SMART_DOOR_SYNC_TEST"


def main():
    try:
        with TemporaryDirectory(prefix="smart-door-test-") as directory:
            outbox = Path(directory) / "outbox.sqlite3"
            client = SupabaseEvents.from_environment(outbox, background=False)
            if client is None:
                return 1
            event_id = client.enqueue(datetime.now(timezone.utc), TEST_LABEL, "DENIED", 0.0)
            if not client.flush_pending():
                print("Test failed. The outbox did not contain the sample event.")
                return 1
    except HTTPError as error:
        report_supabase_error(error)
        return 1
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"The test did not finish ({type(error).__name__}). Check your internet connection and Supabase setup.")
        return 1

    print(f"Supabase accepted the {TEST_LABEL} event.")
    print("Run this in Supabase SQL Editor to confirm the row:")
    print(
        "select occurred_at, person, result, similarity\n"
        "from public.door_events\n"
        f"where id = '{event_id}';"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("\nTest cancelled.") from None
