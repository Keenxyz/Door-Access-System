import {useCallback,useState} from "react";
import {Bell,Monitor,UserRound,Wifi} from "lucide-react";
import {Feedback} from "../components/Feedback";
import {config,getLinks,type Session} from "../services/supabase";
import {readPreference,writePreference,type Theme} from "../services/preferences";
import {useData} from "../services/useData";

export function Settings({session,identity,theme,setTheme,onSignOut}:{session:Session|null;identity:string;theme:Theme;setTheme:(theme:Theme)=>void;onSignOut:()=>void}) {
  const key="unread:"+identity;
  const [unread,setUnread]=useState(()=>readPreference(key,false));
  const load=useCallback(async()=>session?getLinks(session):1,[session]);
  const {data,error,pending,reload}=useData(load,session?12000:0);
  return <>
    <div className="page-heading"><div><h1>Settings</h1><p>Manage this viewer and check its connection to the system.</p></div></div>
    <div className="settings-grid">
      <section className="panel"><h2><UserRound size={20}/> Viewer account</h2><dl className="details"><div><dt>Signed in as</dt><dd>{session?.email??"Demo administrator"}</dd></div><div><dt>Access</dt><dd>{session?"Supabase viewer":"Sample data"}</dd></div></dl><button className="secondary" onClick={onSignOut}>{session?"Sign out":"Exit demo"}</button></section>
      <section className="panel"><h2><Monitor size={20}/> Appearance</h2><label className="setting-field">Color theme<select value={theme} onChange={event=>setTheme(event.target.value as Theme)}><option value="system">Use device setting</option><option value="light">Light</option><option value="dark">Dark</option></select></label></section>
      <section className="panel"><h2><Bell size={20}/> Alert preferences</h2><label className="checkbox"><input type="checkbox" checked={unread} onChange={event=>{setUnread(event.target.checked);writePreference(key,event.target.checked);}}/> Show unread alerts by default</label><p>Alert preferences and read status are stored in this browser.</p></section>
      <section className="panel"><h2><Wifi size={20}/> Device connection</h2><Feedback pending={pending} error={error} reload={reload}/><dl className="details"><div><dt>Supabase project</dt><dd>{session&&config?.url?new URL(config.url).host:session?"Unavailable":"Demo mode"}</dd></div><div><dt>Linked writer accounts</dt><dd>{data??"—"}</dd></div><div><dt>Recognition heartbeat</dt><dd>{session?"Unavailable":"Simulated"}</dd></div></dl></section>
    </div>
  </>;
}
