import webpush from "npm:web-push@3.6.7";

type DoorEvent = { id: string; device_id: string; occurred_at: string; notify: boolean;
  result: string; lock_command: string | null };
type Subscription = { endpoint: string; p256dh: string; auth_key: string };

const project = Deno.env.get("SUPABASE_URL");
const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
const webhookSecret = Deno.env.get("DOOR_WEBHOOK_SECRET");
const publicKey = Deno.env.get("DOOR_VAPID_PUBLIC_KEY");
const privateKey = Deno.env.get("DOOR_VAPID_PRIVATE_KEY");
const subject = Deno.env.get("DOOR_VAPID_SUBJECT");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function response(body: unknown, status = 200) {
  return Response.json(body, {
    status,
    headers: { "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" },
  });
}

async function validSecret(input: string | null) {
  if (!input || !webhookSecret) return false;
  const encode = (value: string) => new TextEncoder().encode(value);
  const hashes = await Promise.all([input, webhookSecret].map((value) =>
    crypto.subtle.digest("SHA-256", encode(value))));
  const first = new Uint8Array(hashes[0]);
  const second = new Uint8Array(hashes[1]);
  return first.reduce((difference, byte, index) => difference | (byte ^ second[index]), 0) === 0;
}

function allowedEndpoint(endpoint: string) {
  try {
    const url = new URL(endpoint);
    const host = url.hostname;
    return url.protocol === "https:" && !url.port && !url.username && !url.password && (
      host === "fcm.googleapis.com" ||
      host === "updates.push.services.mozilla.com" ||
      host === "web.push.apple.com" || host.endsWith(".push.apple.com") ||
      host.endsWith(".notify.windows.com")
    );
  } catch {
    return false;
  }
}

async function db<T>(path: string, method = "GET"): Promise<T> {
  const result = await fetch(project + "/rest/v1/" + path, {
    method, headers: { apikey: serviceKey!, Authorization: "Bearer " + serviceKey },
    signal: AbortSignal.timeout(6000),
  });
  if (!result.ok) throw new Error("Database request failed (" + result.status + ")");
  return (method === "DELETE" ? null : await result.json()) as T;
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: {
      "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "apikey",
    } });
  }
  if (request.method === "GET") {
    return publicKey && privateKey && subject ? response({ publicKey }) : response({ error: "Push is not configured" }, 503);
  }
  if (request.method !== "POST") return response({ error: "Method not allowed" }, 405);
  if (!(await validSecret(request.headers.get("x-door-webhook-secret")))) {
    return response({ error: "Unauthorized" }, 401);
  }
  if (!project || !serviceKey || !publicKey || !privateKey || !subject) {
    return response({ error: "Push is not configured" }, 503);
  }

  try {
    const body = await request.json();
    if (body.type !== "INSERT" || body.schema !== "public" || body.table !== "door_events" ||
        body.record?.result !== "DENIED" || body.record?.notify !== true) return response({ ignored: true });
    const { id, device_id: device } = body.record;
    if (typeof id !== "string" || typeof device !== "string" || !UUID.test(id) || !UUID.test(device)) {
      return response({ error: "Invalid event ID" }, 400);
    }

    const [event] = await db<DoorEvent[]>(
      "door_events?select=id,device_id,occurred_at,notify,result,lock_command&device_id=eq." + device + "&id=eq." + id,
    );
    if (!event?.notify || event.result !== "DENIED") return response({ ignored: true });
    const [pair] = await db<{ reader_id: string }[]>("door_devices?select=reader_id&writer_id=eq." + device);
    if (!pair) return response({ ignored: true });
    const subscriptions = await db<Subscription[]>(
      "door_push_subscriptions?select=endpoint,p256dh,auth_key&viewer_id=eq." + encodeURIComponent(pair.reader_id),
    );

    const message = JSON.stringify({
      title: "Security Alert",
      body: "ACCESS DENIED · UNKNOWN · " + event.occurred_at +
        (event.lock_command === "SECURE_REQUESTED" ? " · Lock command sent" : " · Lock status unverified"),
      timestamp: Date.parse(event.occurred_at), tag: "door:" + device + ":" + id, url: "/#activity",
    });
    const outcomes = await Promise.allSettled(subscriptions.filter(({ endpoint }) => allowedEndpoint(endpoint))
      .map(async (subscription) => {
        try {
          await webpush.sendNotification({
            endpoint: subscription.endpoint,
            keys: { p256dh: subscription.p256dh, auth: subscription.auth_key },
          }, message, {
            TTL: 600,
            timeout: 7000,
            vapidDetails: { subject, publicKey, privateKey },
          });
        } catch (error) {
          const status = (error as { statusCode?: number }).statusCode;
          if (status !== 404 && status !== 410) throw error;
          await db("door_push_subscriptions?endpoint=eq." + encodeURIComponent(subscription.endpoint), "DELETE");
        }
      }));
    const failures = outcomes.filter((result) => result.status === "rejected").length;
    if (failures) return response({ error: "Push delivery failed", failures }, 502);
    return response({ ok: true });
  } catch {
    return response({ error: "Could not process the door alert" }, 500);
  }
});
