import {useCallback} from "react";
import {Link} from "react-router-dom";
import {Activity,ArrowRight,Check,LockKeyhole,ScanFace,Users,X} from "lucide-react";
import {StatusCard} from "../components/StatusCard";
import {AccessTable} from "../components/AccessTable";
import {Feedback} from "../components/Feedback";
import {demoPage} from "../services/demo";
import {getCount,getEvents,getLinks,type Session,type Event} from "../services/supabase";
import {useData} from "../services/useData";

function ActivityChart({rows}:{rows:Event[]}) {
  const start=new Date();
  start.setHours(0,0,0,0);
  const days=Array.from({length:7},(_,i)=>{
    const day=new Date(start);
    day.setDate(day.getDate()+i-6);
    const next=new Date(day);
    next.setDate(day.getDate()+1);
    const events=rows.filter(row=>{const time=Date.parse(row.occurred_at);return time>=+day&&time<+next;});
    const granted=events.filter(row=>row.result==="GRANTED").length;
    return {day,granted,denied:events.length-granted};
  });
  const max=Math.max(1,...days.map(day=>day.granted+day.denied));
  return <div className="chart">{days.map(({day,granted,denied})=><div className="chart-day" key={+day}>
    <span aria-hidden="true">{granted+denied}</span>
    <div className="chart-track" role="img" aria-label={day.toLocaleDateString()+": "+granted+" granted, "+denied+" denied"}>
      <i className="bar granted" style={{height:granted/max*100+"%"}}/><i className="bar denied" style={{height:denied/max*100+"%"}}/>
    </div>
    <span aria-hidden="true">{day.toLocaleDateString(undefined,{weekday:"short"})}</span>
  </div>)}</div>;
}

export function Dashboard({session,demo,userCount}:{session:Session|null;demo:boolean;userCount:number}) {
  const load=useCallback(async()=>{
    const query={page:0,size:100};
    if(!session) return {events:demoPage(query),granted:demoPage({...query,result:"GRANTED"}).total,denied:demoPage({...query,result:"DENIED"}).total,links:1};
    const [events,granted,denied,links]=await Promise.all([getEvents(session,query),getCount(session,"GRANTED"),getCount(session,"DENIED"),getLinks(session)]);
    return {events,granted,denied,links};
  },[session]);
  const {data,error,pending,reload}=useData(load,demo?0:12000);
  return <>
    <div className="page-heading"><div><h1>Access overview</h1><p>Monitor facial recognition activity and review door access decisions.</p></div><Link className="primary button" to="/logs">View access logs <ArrowRight size={17}/></Link></div>
    <Feedback pending={pending} error={error} reload={reload}/>
    <div className="stat-grid">
      <StatusCard icon={LockKeyhole} label="Door status" value={demo?"LOCKED":"UNKNOWN"} detail={demo?"Simulated door state":"Physical door sensor status unavailable"} tone={demo?"green":"muted"}/>
      <StatusCard icon={Users} label="Registered users" value={demo?userCount:"—"} detail={demo?"Demo roster":"Enrollment data is local"}/>
      <StatusCard icon={Check} label="Access granted" value={data?.granted??"—"} detail="All available granted events"/>
      <StatusCard icon={X} label="Access denied" value={data?.denied??"—"} detail="All available denied events" tone="red"/>
    </div>
    <div className="dashboard-grid">
      <section className="panel chart-panel"><div className="section-head"><div><h2>Recognition activity</h2><p>Last 7 days from the 100 most recent events</p></div><div className="chart-legend"><span><i className="granted"/>Granted</span><span><i className="denied"/>Denied</span></div></div>{data?<ActivityChart rows={data.events.rows}/>:<p className="empty">Activity will appear when records load.</p>}</section>
      <section className="panel system-panel"><div className="section-head"><div><h2>System status</h2><p>Recognition and viewer connection</p></div><span className="stat-icon green"><Activity size={19}/></span></div>
        <dl className="details"><div><dt><ScanFace size={16}/> Face recognition</dt><dd>{demo?"Simulated active":"Unknown"}</dd></div><div><dt>Linked writer accounts</dt><dd>{data?.links??"—"}</dd></div><div><dt>Event source</dt><dd>{demo?"Sample records":data?error?"Last successful check":"Supabase reachable":"Awaiting check"}</dd></div></dl>
        <Link className="text-link" to="/settings">Device and account settings <ArrowRight size={16}/></Link>
      </section>
    </div>
    <section className="panel"><div className="section-head"><div><h2>Recent activity</h2><p>The latest recognition decisions</p></div><Link className="text-link" to="/logs">Full history <ArrowRight size={16}/></Link></div>{data&&(data.events.rows.length?<AccessTable rows={data.events.rows.slice(0,5)}/>:<p className="empty">No recognition events are visible to this viewer.</p>)}</section>
  </>;
}
