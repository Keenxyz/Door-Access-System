type Config = { url: string; key: string };
declare const __DOOR_CONFIG__: Config | null;
export const config = __DOOR_CONFIG__;
export type Decision = "GRANTED" | "DENIED";
export type Event = { id: string; device_id: string; occurred_at: string; person: string; result: Decision; similarity: number; photo_path?: string | null; lock_command?: string | null };
export type Session = { token: string; email: string; id: string };
export type Query = { page: number; size: number; search?: string; result?: Decision; includeTests?: boolean };
export const eventKey = (event: Event) => event.device_id + ":" + event.id;
export const displayName = (event: Event) => event.person === "UNKNOWN" ? "Unknown visitor" : event.person === "SMART_DOOR_SYNC_TEST" ? "Connection test" : event.person;
export const formatDate = (date: string) => new Intl.DateTimeFormat(undefined, {dateStyle:"medium",timeStyle:"short"}).format(new Date(date));

class ApiError extends Error {
  constructor(public status: number, public code?: string) { super(status===401 ? "Your session expired. Sign in again." : "Supabase could not load this data."); }
}
export const isExpired = (error: unknown) => error instanceof ApiError && error.status === 401;

export async function signIn(email: string, password: string): Promise<Session> {
  if (!config) throw new Error("Add a Supabase project URL and publishable key, or open the demo.");
  const response = await fetch(config.url + "/auth/v1/token?grant_type=password", {
    method:"POST", headers:{ apikey:config.key,"Content-Type":"application/json" },
    body:JSON.stringify({ email, password }), redirect:"error", signal:AbortSignal.timeout(12000),
  });
  if (!response.ok) throw new Error(response.status === 429 ? "Too many attempts. Try again in a minute." : "Sign-in failed. Check your viewer email and password.");
  const data = await response.json();
  if (!data.access_token || !data.user?.id) throw new Error("No viewer session returned by Supabase.");
  return { token:data.access_token, email:data.user.email || email, id:data.user.id };
}

async function api(session: Session, path: string, init: RequestInit = {}) {
  if (!config) throw new Error("Supabase configuration missing.");
  const response = await fetch(config.url + path, {
    ...init, headers:{apikey:config.key, Authorization:"Bearer "+session.token, ...init.headers},
    redirect:"error", cache:"no-store", signal:init.signal || AbortSignal.timeout(12000),
  });
  if (!response.ok) {
    const data = await response.json().catch(()=>null);
    throw new ApiError(response.status, data?.code);
  }
  return response;
}

function filters(query: Query) {
  const params = new URLSearchParams();
  if (!query.includeTests) params.append("person","neq.SMART_DOOR_SYNC_TEST");
  const term = query.search?.trim().replace(/[\\%_*]/g, "\\$&");
  if (term) params.append("person","ilike.%" + term + "%");
  if (query.result) params.set("result","eq."+query.result);
  return params;
}
const count = (response: Response) => {
  const total = response.headers.get("Content-Range")?.split("/")[1];
  return total && /^\d+$/.test(total) ? Number(total) : null;
};

export async function getEvents(session: Session, query: Query) {
  const params = filters(query);
  const columns = "id,device_id,occurred_at,person,result,similarity";
  params.set("select", columns + ",photo_path,lock_command");
  params.set("limit",String(query.size));
  params.set("offset",String(query.page * query.size));
  params.set("order","occurred_at.desc,id.desc,device_id.desc");
  const fetchPage = () => api(session,"/rest/v1/door_events?"+params,{headers:{Prefer:"count=exact"}});
  let response;
  try { response = await fetchPage(); }
  catch (error) {
    if (!(error instanceof ApiError) || !["42703","PGRST204"].includes(error.code ?? "")) throw error;
    params.set("select",columns);
    response = await fetchPage();
  }
  return { rows: await response.json() as Event[], total: count(response) };
}
export async function getLinks(session: Session) {
  const result = await api(session,"/rest/v1/door_devices?select=writer_id");
  return (await result.json() as {writer_id:string}[]).length;
}
export async function getCount(session: Session, result: Decision) {
  const params = filters({page:0,size:1,result});
  params.set("select","id");
  params.set("limit","1");
  return count(await api(session,"/rest/v1/door_events?"+params,{method:"HEAD",headers:{Prefer:"count=exact"}}));
}
export async function getPhoto(session: Session, path: string, signal: AbortSignal) {
  const uuid = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}";
  if (!new RegExp("^"+uuid+"/"+uuid+"\\.jpg$","i").test(path)) throw new Error("Invalid photo reference.");
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const response = await api(session,"/storage/v1/object/authenticated/door-visitor-images/"+encoded,{signal});
  if (!response.headers.get("content-type")?.startsWith("image/jpeg")) throw new Error("Unexpected image.");
  return response.blob();
}
