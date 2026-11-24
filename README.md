# Smart Door Security

The Windows PC runs YuNet and SFace against its webcam and enrolled faces. Each new recognition decision goes to `access_logs.csv`. With Supabase enabled, the PC also queues events in `door_event_outbox.sqlite3` and retries uploads after a connection failure. Restart recognition to resume syncing pending events. Older CSV rows are local history.

The phone viewer shows up to 100 recent Supabase records, with granted and denied counts, a seven-day activity chart, a pairing check, and a searchable access log. You can filter by name, decision, and date, then export the displayed records as CSV. Turn on **Show connection tests** to see synthetic smoke test events. It updates automatically while visible, with periodic checks as a fallback for Supabase Realtime. It shows the name or unknown-face label, decision, similarity, and event time in the phone's timezone. Face embeddings stay on the recognition device. Visitor photos are optional and can be uploaded to a private Supabase bucket. The Pi can drive a relay after liveness and installation checks. Physical door position requires a sensor.

See the [Raspberry Pi door controller guide](docs/raspberry-pi-door-controller.md) for Windows simulation, GPIO bench tests, SSH deployment, automatic startup with systemd, SSD1306 setup, Windows display simulation, and owner alerts.

## Source on GitHub

This repository contains the Raspberry Pi application, systemd installer, Supabase migrations, tests, and the standalone React dashboard in `smart-door-ui/`. The existing `phone/` viewer has its own Git repository and is kept local to that checkout.

Install dependencies after cloning. Copy the model files and enrollment data directly to your Pi using the [Pi setup guide](docs/raspberry-pi-door-controller.md). Local credentials, enrollment data, access logs, and visitor photos are excluded from the repository.


## Set up Supabase

1. Open a Supabase project. In **SQL Editor**, run [the migration](supabase/migrations/202611230001_door_events.sql) once.
2. In **Authentication → Users**, create two confirmed email/password users. Use one as the PC writer and the other as the phone viewer. Copy their user UUIDs.
3. Run this in **SQL Editor** with the two UUIDs.

   ```sql
   insert into public.door_devices (writer_id, reader_id)
   values ('PC_WRITER_UUID', 'PHONE_VIEWER_UUID');
   ```

4. Copy the project URL and the `sb_publishable_…` key from the project's Connect dialog or API Keys settings. The writer can submit events for its own device. The viewer can read events for devices assigned to it. These permissions are enforced by Postgres. [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys) · [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)

## Enable instant updates in Supabase

Run the [Realtime migration](supabase/migrations/202611230002_door_events_realtime.sql) once in the project's SQL Editor. It adds only the door event table to the existing Realtime publication. The dashboard subscribes with the viewer's existing permissions and also checks for updates every four seconds while visible. [Supabase Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes)

## Run recognition on Windows

From the project folder, run this in PowerShell.

```powershell
.\.venv\Scripts\python.exe .\src\recognize_face.py
```

Recognition starts without an email or password prompt. With an unconfigured or rejected writer it logs to CSV only. To keep updating the Supabase viewer on Windows, verify and save the paired writer login once:

```powershell
.\.venv\Scripts\python.exe .\src\recognize_face.py --setup-writer
```

Use the PC writer account and run subsequent recognition sessions under the same Windows account. The writer login is encrypted for that account. The public project URL and publishable key come from `dashboard.local.json` (`project_url` and `publishable_key`), or from `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Recognition can also use `SUPABASE_DEVICE_EMAIL` and `SUPABASE_DEVICE_PASSWORD` supplied to the process. Run setup again if the Windows writer credentials change. Use `--local-only` to select CSV only or `--supabase` to require a configured, authorized writer. Temporary network failures still queue events for retry. **Supabase confirmed upload** means the viewer can read the event.

Run `.\.venv\Scripts\python.exe .\src\enroll_face.py` to enroll a face. The first run creates a separate enrollment password of at least 12 characters. Later runs ask for that password before opening the camera. The verifier is stored in `dataset/.enrollment-auth.json`. Keep write access to the application and enrollment data limited to trusted OS accounts. Press **Q** in either camera window to stop.


## Retry scans already queued on the PC

Run this from the project folder to upload pending scans without reopening the camera.

```powershell
.\.venv\Scripts\python.exe .\src\recognize_face.py --sync-pending
```

Configure the same PC writer account used when recording the scans before running the retry. After seeing **Supabase confirmed upload**, the dashboard will update automatically. The retry uses the existing queue; CSV-only scans stay in the local log.

## Test the Supabase connection without a camera

After pairing the PC writer and phone viewer, open PowerShell in this folder and run:

```powershell
.\.venv\Scripts\python.exe .\src\test_supabase_sync.py
```

Set up the paired writer first using the same configuration as recognition. The script uploads one synthetic `SMART_DOOR_SYNC_TEST` event through the same authentication, queue, and upload code as recognition. If Supabase accepts the upload, paste the printed query into **SQL Editor** to find the exact test row. Sign in to the viewer and turn on **Show connection tests** to check that it sees the event.

## Open the dashboard on localhost

Start the dashboard in a separate PowerShell terminal from the project folder.

```powershell
.\.venv\Scripts\python.exe .\src\serve_dashboard.py
```

Open [http://localhost:8000](http://localhost:8000). The URL and publishable key from `dashboard.local.json` are filled in under **Supabase project**. Sign in with your **phone viewer** account. This page loads the dashboard from the PC and reads events directly from Supabase. Keep recognition running in the other terminal to record fresh events. Press **Ctrl+C** in the dashboard terminal to stop the local server.

The signed-in viewer sees events only from the writers assigned to it in door_devices. For reciprocal pairings, use the PC writer and viewer from the same pairing row when testing a new scan.

The local server binds to the Windows PC only. Open it in a browser on that PC. If port 8000 is in use, start it with `--port 8001` and open [http://localhost:8001](http://localhost:8001).

## Open and install Smart Door on a phone

Open **[Door Access System](https://facial-recognition-door-access-system-raspberry-pi-3-model-b.ingeniousfable4.chatgpt.site)** in the phone browser. Anyone with the link can open the sign-in page. The project is prefilled and access records require a paired **Supabase viewer** account.

- On **Android**, open the website in Chrome. From the Chrome menu, choose **Add to Home screen**, then **Install**. You can also use **Install app** in Smart Door when Chrome offers it.
- On **iPhone**, open the website in Safari. Tap **Share → Add to Home Screen**, turn on **Open as Web App** if shown, then tap **Add**.

The Home Screen app updates from Supabase while open. Keep recognition running on the PC to record new attempts. The app shell can open after being cached, and viewing fresh records requires an internet connection.

## Edit the dashboard UI

The page, navigation, sign-in form, setup, and installation dialog are in `phone/src/Dashboard.tsx`. The overview, activity chart, and access log are in `phone/src/ActivityView.tsx`. Supabase sign-in and subscriptions are in `phone/src/activity.ts`.

On Windows, run `.\build-dashboard.cmd` from the project folder after changing the UI. The launcher can use Node.js bundled with Visual Studio 2022 Community if npm is missing from your terminal.

If npm is already available on your system, you can also run `npm ci` once in the `phone` folder and then `npm run build`. The build type-checks the source and writes `phone/dist/app.js` for the local server and hosted site.

The public website updates when a new Site version is published.
