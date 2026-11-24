import {useCallback,useState} from "react";
import {NotificationCard} from "../components/NotificationCard";
import {Feedback} from "../components/Feedback";
import {demoPage} from "../services/demo";
import {eventKey,getEvents,type Session} from "../services/supabase";
import {readPreference,writePreference} from "../services/preferences";
import {useData} from "../services/useData";

export function Notifications({session,identity}:{session:Session|null;identity:string}) {
  const key="read:"+identity;
  const [read,setRead]=useState<string[]>(()=>readPreference(key,[]));
  const [onlyUnread,setOnlyUnread]=useState(()=>readPreference("unread:"+identity,false));
  const load=useCallback(async()=>{
    const query={page:0,size:50,result:"DENIED" as const};
    return session?getEvents(session,query):demoPage(query);
  },[session]);
  const {data,error,pending,reload}=useData(load,session?12000:0);
  const rows=data?.rows.filter(row=>!onlyUnread||!read.includes(eventKey(row)))??[];
  function toggle(id:string) {
    const next=read.includes(id)?read.filter(item=>item!==id):[...read,id];
    setRead(next);
    writePreference(key,next);
  }
  return <>
    <div className="page-heading"><div><h1>Notifications</h1><p>In-app alerts from the 50 most recent denied access events.</p></div><label className="checkbox"><input type="checkbox" checked={onlyUnread} onChange={event=>setOnlyUnread(event.target.checked)}/> Unread only</label></div>
    <Feedback pending={pending} error={error} reload={reload}/>
    {data&&(rows.length?<div className="notification-list">{rows.map(event=><NotificationCard key={eventKey(event)} event={event} session={session} read={read.includes(eventKey(event))} onToggle={()=>toggle(eventKey(event))}/>)}</div>:<p className="panel empty">{onlyUnread?"No unread alerts in the latest events.":"No denied access events are visible to this viewer."}</p>)}
  </>;
}
