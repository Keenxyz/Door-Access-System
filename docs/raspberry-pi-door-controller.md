# Raspberry Pi door controller

## What to test first

From the VS Code PowerShell terminal at the project root:

```powershell
.\.venv\Scripts\python.exe .\src\recognize_face.py --simulate
.\.venv\Scripts\python.exe .\src\recognize_face.py --local-only
```

1. The first command runs synthetic granted and denied visits. Expect a green/unlock command for five seconds, then secure/off. Expect a red/secure command for five seconds, then both LEDs off. It uses no camera, GPIO, real identities, or Supabase writes.
2. The second command uses your webcam and existing enrollments. Run `enroll_face.py` first if needed. Hold a registered face steady for at least three frames, then leave the frame for at least 1.2 seconds. Test a single unregistered face and then two people together. The preview shows which outcome was accepted, and `access_logs.csv` keeps its existing four-column format.
3. For cloud sync on Windows, run `recognize_face.py --setup-writer` once with the PC **writer** login, then start recognition normally. Open the viewer with the paired **reader** account. Watch for **Supabase confirmed upload**. An older paired account can be both a viewer and writer for different devices, so match the same pairing row.
4. Run Windows with `--pad-model models/anti-spoof-mn3.onnx` to test the liveness preview before the Pi bench test. Follow the randomized head-turn prompts. Try a printed photo and different video replays with the relay disconnected. A failed or interrupted challenge may require stepping out of view before trying again.

## Pi installation and SSH

Use Raspberry Pi Imager to configure Raspberry Pi OS, your username, network, and SSH. Prefer SSH keys and connect from your local network. [Raspberry Pi Imager](https://www.raspberrypi.com/documentation/computers/imager.html) · [Raspberry Pi SSH](https://www.raspberrypi.com/documentation/computers/remote-access.html)

Open Windows PowerShell in your local project folder. Replace `YOUR_USER` with the username you configured on the Pi and `raspberrypi.local` with its hostname or IP address.

```powershell
ssh YOUR_USER@raspberrypi.local 'mkdir -p ~/smart-door-security'
scp -r src models deploy YOUR_USER@raspberrypi.local:~/smart-door-security/
ssh YOUR_USER@raspberrypi.local 'mkdir -m 700 -p ~/smart-door-security/dataset'
scp dataset/authorized_faces.json YOUR_USER@raspberrypi.local:~/smart-door-security/dataset/
ssh YOUR_USER@raspberrypi.local
```

Use Raspberry Pi OS Lite with OpenCV 4.8 or newer. The supported package in Trixie is suitable. The enrollment file contains biometric templates. Copy it directly to your Pi and keep it out of GitHub.

The last SSH command opens the Pi terminal. Wait until you see a prompt like `YOUR_USER@raspberrypi:~ $`. Then run the following commands inside that session.

```bash
cd ~/smart-door-security
chmod 700 dataset
chmod 600 dataset/authorized_faces.json
sudo apt update
sudo apt install -y python3-venv python3-opencv python3-numpy python3-gpiozero python3-lgpio espeak-ng alsa-utils v4l-utils
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -c "import cv2, gpiozero; print(cv2.__version__); print(hasattr(cv2, 'FaceDetectorYN'))"
python src/recognize_face.py --simulate
```

Use a USB/UVC camera available to OpenCV as a video device. Set `--camera 1` if it appears as the second device. A Raspberry Pi CSI camera may need a different acquisition backend depending on the OS. In a local desktop session, omit `--no-preview` to see the window. Over SSH, a headless run uses the OS default audio device for spoken liveness prompts.

Test the speaker alone from the Pi first.

```bash
espeak-ng 'Access Granted. Welcome!'
espeak-ng 'Access Denied. Unauthorized Person Detected!'
```

Select the USB speaker or 3.5 mm jack as the default output using your Pi OS audio settings. The speaker connects to the USB or audio jack.

## GPIO and relay bench test

The Raspberry Pi GPIO inputs and outputs are **3.3 V logic**. Never feed 5 V or 12 V into a GPIO. Check pin numbering with `pinout` on the Pi. [Raspberry Pi GPIO specifications](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) · [GPIO Zero output device behavior](https://gpiozero.readthedocs.io/en/stable/api_output.html)

| Component | BCM GPIO | Physical pin | Bench connection |
|---|---:|---:|---|
| Green LED | 17 | 11 | GPIO through its own 330 ohm resistor to the LED anode. Cathode to GND. |
| Red LED | 27 | 13 | GPIO through its own 330 ohm resistor to the LED anode. Cathode to GND. |
| Relay control | 23 | 16 | Relay input through a verified 3.3 V-compatible interface. |
| Future doorbell | 22 | 15 | Reserved. |
| Ground | — | 6 | LED return and relay logic reference if the relay module requires a shared reference. |

Power the relay module as specified by its datasheet. A board with a 5 V input pull-up or drive requirement needs a suitable driver or isolator. Confirm what the relay input sees while the Pi is booting, rebooting, or stopped. The inactive GPIO level is maintained by the hardware interface, typically an appropriate external pull-up or pull-down. Software sets the relay inactive when it acquires GPIO 23.

1. Keep the **solenoid and 12 V circuit disconnected** from COM, NO and NC. Power only the Pi and the verified relay module logic.
2. With a multimeter in continuity mode on the isolated relay contacts, identify COM–NC at rest and COM–NO when energized. Confirm your relay input polarity with its datasheet.
3. Run the bench command, substituting the polarity you verified. Type `DISCONNECTED` at the prompt.

```bash
python src/recognize_face.py --relay-bench --relay-active low
```

4. Confirm the contacts switch once and return to rest after five seconds. Repeat while stopping with Ctrl+C during the pulse. Check idle contact state after a full Pi reboot.
5. Run the camera with real LEDs and speech while the relay and solenoid load remain disconnected.

```bash
python src/recognize_face.py --hardware --no-preview --local-only --pad-model models/anti-spoof-mn3.onnx
```

## Confirm the 12 V lock before connecting the load

The provided description identifies a **mini 12 V DC cabinet latch**. It gives no exact part number, rated current, duty cycle, polarity requirement or energized bolt behavior. Its wiring is still conditional. Obtain the datasheet or have the latch bench-tested off the door by someone qualified, with a current-limited supply set to the verified rating. Record what happens with power applied and removed. A momentary-duty cabinet latch must never be energized continuously. Keep this prototype on a cabinet or isolated bench until the access hardware is suitable for the intended door and route.

| Confirmed type | Behavior | Contact plan when relay activation means unlock |
|---|---|---|
| Power-to-unlock | Energizing the latch releases it | Use the normally open contact with a suitable circuit. Loss of power leaves the latch in its unpowered state. |
| Power-to-lock | Energizing the lock secures it | A suitable continuous-duty lock can use the normally closed contact, so activating the relay interrupts lock power. Loss of lock power releases it. |

The qualified installer must select the separate fused 12 V supply, relay or driver rated for the DC inductive load and its inrush, and manufacturer-compatible suppression across the load. A DC flyback diode or clamp must suit the lock's required release speed and polarity. Keep 12 V off the Pi logic circuit, provide a manual release and independent safe egress, and verify behavior during power loss and a stalled controller. Use rated door hardware and an independent limiter where a stuck relay or overlong pulse is hazardous. These requirements apply before attaching a live lock.

After this checklist and successful spoof tests, the software accepts an explicit hardware enable command. This example uses **power-to-unlock and active-low only when both were independently verified**.

```bash
python src/recognize_face.py --hardware --enable-unlock --relay-active low \
  --lock-type power-to-unlock --pad-model models/anti-spoof-mn3.onnx --no-preview --supabase
```

A grant starts a five-second pulse, then switches the relay inactive with green off. A person walking out of the frame does not shorten the pulse. Each face is tracked and confirmed independently. A group with at least one registered person who passes liveness can trigger one unlock. Unknown visitors in the same group are logged separately, with a cropped photo if enabled. An unknown-only group drives secure/red. A denial, ambiguous remaining faces, or a shutdown can secure the relay early.

The camera starts recognizing immediately. With the relay enabled, each registered person still needs to pass the liveness challenge. Follow the prompt addressed to the current person. An individual face starts a new visit after being out of view for `--leave-seconds`. Continuous recognition does not repeatedly unlock the door. New groups still respect `--unlock-cooldown`. Unknown alerts respect `--notification-cooldown`. The recognition threshold is `--threshold` and stability is `--confirm-frames`.

The RGB liveness gate combines random head turns and a passive presentation-attack model. This is prototype protection. Test it on the installed camera against controlled prints and replays, and use a validated PAD sensor and independent second factor for a production entry point. The UI records a secure command and leaves actual door position unverified until a door-position sensor is installed. [Open Model Zoo PAD model](https://docs.openvino.ai/2023.3/omz_models_model_anti_spoof_mn3.html) · [NIST biometric presentation attack guidance](https://pages.nist.gov/800-63-4/sp800-63b.html)

## Start automatically at boot

After copying the files and installing the packages, run these commands inside the Pi SSH session. The `cd` command opens the Pi project folder.

```bash
cd ~/smart-door-security
sudo sh deploy/install-pi.sh
```

The installer enables `smart-door.service` for future boots. It creates a dedicated `smart-door` system account, grants the service the `gpio`, `video`, and `audio` groups, and installs the read-only application and enrollment file under `/opt/smart-door`. Local CSV logs, the SQLite outbox and optional local photos are in `/var/lib/smart-door`. Device checks run with the same permissions as recognition. Shutdown sends SIGTERM so Python can secure GPIO and release the webcam. Failed runs retry after 10 seconds with a systemd start limit.

### Finish the initial setup

1. Keep the relay and 12 V lock disconnected. Find the correct camera and speaker on the Pi.

   ```bash
   v4l2-ctl --list-devices
   ls -l /dev/v4l/by-id/
   aplay -l
   aplay -L
   sudoedit /etc/smart-door/smart-door.env
   ```

   Set `SMART_DOOR_CAMERA` to the USB capture device. Prefer its `/dev/v4l/by-id/…-video-index0` path when available. Set `SMART_DOOR_ALSA_DEVICE` to the working ALSA output, such as `plughw:CARD=Device,DEV=0` with your own card name, or keep `default` if it works. The boot service uses ALSA directly and doesn't depend on a logged-in desktop audio session.

2. For Supabase, put the project URL, publishable key, and paired writer email in the same settings file. On the Pi, run this command in a terminal to enter the password without showing it on screen or including it in shell history.

   ```bash
   sudo bash -c 'IFS= read -rs -p "Supabase writer password: " password && [ -n "$password" ] && printf "%s" "$password" > /etc/smart-door/writer-password'
   ```

   systemd supplies the password as a credential. With a configured writer, events queue locally while offline and upload when the connection returns. With no configured writer, events go to the CSV. Follow [Supabase alerts and photos](#supabase-alerts-and-photos) to receive alerts on the viewer.

3. Start the relay-disabled service, check the logs, and test both a registered face and an unknown visitor.

   ```bash
   sudo systemctl start smart-door.service
   systemctl status smart-door.service --no-pager
   sudo journalctl -u smart-door.service -b -f
   ```

   Confirm the green and red LEDs and the spoken announcements. With sync configured, look for **Supabase confirmed upload** and verify the events in your viewer. Reboot once with `sudo reboot`, then check the service status and this boot's journal. After setup it will start without an SSH session. If startup hits its retry limit after a device or configuration failure, correct the cause and run `sudo systemctl reset-failed smart-door.service` followed by `sudo systemctl start smart-door.service`.

### Enable the relay after bench testing

Complete the GPIO, load-disconnected relay, and anti-spoof tests above before enabling the relay on boot. To run the manual relay test with GPIO and the webcam free, stop the service with `sudo systemctl stop smart-door.service`. For a headless liveness test with the lock disconnected, set `SMART_DOOR_ARGS=--pad-model /opt/smart-door/models/anti-spoof-mn3.onnx` and restart the service.

After verification, edit `/etc/smart-door/smart-door.env` and add the relay options to `SMART_DOOR_ARGS`. This example is for a verified active-low relay and verified power-to-unlock latch.

```dotenv
SMART_DOOR_ARGS="--enable-unlock --relay-active low --lock-type power-to-unlock --pad-model /opt/smart-door/models/anti-spoof-mn3.onnx"
```

Run `sudo systemctl restart smart-door.service`. Keep the standalone emergency release and independently verified idle relay state described above. To update the installed code or enrollment file from your Pi source checkout, stop the service, rerun the installer, then start it again. The installer preserves the service configuration and runtime logs.


## Supabase alerts and photos

1. In your project's SQL Editor, run [the door alerts and photos migration](../supabase/migrations/202611230003_door_alerts_and_photos.sql). Run the [Realtime migration](../supabase/migrations/202611230002_door_events_realtime.sql) if it hasn't been applied.
2. Scan an unknown face once with the viewer open. The camera records the event and sends it through the existing queue. The viewer shows a Security Alert when it receives a new alert-eligible denial. Confirm the timestamp and result in `public.door_events`. Try holding the face in view and returning within the cooldown. The ongoing detection produces no repeated alert.
3. For optional photos, add `--capture-unknown`. The uploader sends the event first so a photo failure doesn't delay the alert. It then uploads a cropped JPEG to the **private** bucket and attaches its reference. Check `photo_path` on the event and use **Show visitor photo** in the viewer. Without Supabase, opt-in photos are stored in the private local `event_photos` folder. Define retention and inform people before enabling capture.
4. To get alerts while the viewer is closed, run [the push subscriptions migration](../supabase/migrations/202611230004_door_push_subscriptions.sql). On a machine with the supported Supabase CLI, use `npx web-push generate-vapid-keys --json` to generate keys and place the following values in an untracked secrets file. Use a long random value for the webhook secret.

```dotenv
DOOR_VAPID_PUBLIC_KEY=YOUR_PUBLIC_VAPID_KEY
DOOR_VAPID_PRIVATE_KEY=YOUR_PRIVATE_VAPID_KEY
DOOR_VAPID_SUBJECT=mailto:YOUR_ADMIN_EMAIL
DOOR_WEBHOOK_SECRET=YOUR_RANDOM_WEBHOOK_SECRET
```

Deploy the server-only [door-alerts function](../supabase/functions/door-alerts/index.ts) and configure its secrets. Replace `PROJECT_REF` and use your untracked secrets file.

```bash
supabase secrets set --project-ref PROJECT_REF --env-file .env
supabase functions deploy door-alerts --project-ref PROJECT_REF --no-verify-jwt
```

The GET returns the public VAPID key. The POST checks the webhook secret and confirms the stored event and owner pairing before sending. Set an **INSERT** Database Webhook on `public.door_events`, using POST to `https://PROJECT_REF.supabase.co/functions/v1/door-alerts` and the custom header `x-door-webhook-secret` with your secret. Keep secrets out of the repository and browser. The Supabase service-role key is accessed by the deployed function and stays server-side. Push text omits photos, and the app opens the viewer-protected image.

In the signed-in viewer on your phone, go to **Setup & help → Phone notifications → Enable alerts** and allow permission. On iPhone, do this from the installed Home Screen app. Sign out to remove that phone's subscription or use **Turn off**. [Supabase Database Webhooks](https://supabase.com/docs/guides/database/webhooks) · [Supabase Edge Functions](https://supabase.com/docs/guides/functions)
