export type Theme="system"|"light"|"dark";

export function readPreference<T>(key:string,fallback:T):T {
  try {
    const value=localStorage.getItem("smart-door-ui:"+key);
    return value===null?fallback:JSON.parse(value) as T;
  } catch {return fallback;}
}

export function writePreference(key:string,value:unknown) {
  try {localStorage.setItem("smart-door-ui:"+key,JSON.stringify(value));} catch { /* browser storage is optional */ }
}
