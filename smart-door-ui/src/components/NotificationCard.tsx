import {useEffect,useState} from "react";
import {Image,ShieldAlert} from "lucide-react";
import {formatDate,getPhoto,type Event,type Session} from "../services/supabase";

function VisitorPhoto({session,path}:{session:Session;path:string}) {
  const [image,setImage]=useState<{url?:string;error?:string}>({});
  useEffect(()=>{
    const controller=new AbortController();
    let url:string|undefined;
    getPhoto(session,path,controller.signal).then(blob=>{
      if(controller.signal.aborted) return;
      url=URL.createObjectURL(blob);
      setImage({url});
    }).catch(()=>{if(!controller.signal.aborted) setImage({error:"The visitor image is unavailable."});});
    return ()=>{controller.abort();if(url) URL.revokeObjectURL(url);};
  },[session,path]);
  if(image.error) return <p role="alert">{image.error}</p>;
  if(!image.url) return <p role="status">Loading visitor photo…</p>;
  return <img className="visitor-photo" src={image.url} alt="Visitor captured during the denied access attempt"/>;
}

export function NotificationCard({event,read,onToggle,session}:{event:Event;read:boolean;onToggle:()=>void;session:Session|null}) {
  const [showPhoto,setShowPhoto]=useState(false);
  return <article className="panel notification-card">
    <span className="stat-icon red"><ShieldAlert size={20}/></span>
    <div><div className="notification-heading"><h2>Access denied</h2><span className={"read-badge "+(read?"read":"unread")}>{read?"Read":"Unread"}</span></div>
      <p>{event.person==="UNKNOWN"?"An unregistered visitor was detected.":event.person+" was denied access."}</p>
      <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
      {event.lock_command&&<p>Lock command <strong>{event.lock_command}</strong></p>}
      {session&&event.photo_path&&<div className="photo-area"><button className="secondary" onClick={()=>setShowPhoto(value=>!value)} aria-expanded={showPhoto}><Image size={16}/> {showPhoto?"Hide visitor photo":"View visitor photo"}</button>{showPhoto&&<VisitorPhoto session={session} path={event.photo_path}/>}</div>}
    </div>
    <button className="secondary" onClick={onToggle}>{read?"Mark as unread":"Mark as read"}</button>
  </article>;
}
