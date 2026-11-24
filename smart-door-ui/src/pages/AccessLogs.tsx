import {useCallback,useState} from "react";
import {ChevronLeft,ChevronRight,Search} from "lucide-react";
import {AccessTable} from "../components/AccessTable";
import {Feedback} from "../components/Feedback";
import {demoPage} from "../services/demo";
import {getEvents,type Decision,type Session} from "../services/supabase";
import {useData} from "../services/useData";

export function AccessLogs({session}:{session:Session|null}) {
  const [search,setSearch]=useState("");
  const [term,setTerm]=useState("");
  const [result,setResult]=useState<Decision|"">("");
  const [page,setPage]=useState(0);
  const size=15;
  const load=useCallback(async()=>{
    const query={page,size,search:term.toLowerCase()==="unknown visitor"?"UNKNOWN":term,result:result||undefined};
    return session?getEvents(session,query):demoPage(query);
  },[session,page,result,term]);
  const {data,pending,error,reload}=useData(load,session?12000:0);
  const pages=data?.total==null?null:Math.max(1,Math.ceil(data.total/size));
  const canAdvance=pages===null?data?.rows.length===size:page+1<pages;
  return <>
    <div className="page-heading"><div><h1>Access logs</h1><p>Review who was recognized, when it happened, and the recorded decision.</p></div></div>
    <section className="panel">
      <form className="filters" onSubmit={event=>{event.preventDefault();setTerm(search.trim());setPage(0);}}>
        <label className="filter-search">Person<div className="searchbox"><Search size={18}/><input type="search" value={search} onChange={event=>setSearch(event.target.value)} maxLength={100} placeholder="Search by name"/></div></label>
        <label>Result<select value={result} onChange={event=>{setResult(event.target.value as Decision|"");setPage(0);}}><option value="">All results</option><option>GRANTED</option><option>DENIED</option></select></label>
        <button className="primary" type="submit">Search</button>
      </form>
      <Feedback pending={pending} error={error} reload={reload}/>
      {data&&(data.rows.length?<AccessTable rows={data.rows}/>:<p className="empty">No access events match these filters.</p>)}
      <div className="pagination"><span>{pages===null?"Page "+(page+1):"Page "+(page+1)+" of "+pages+" · "+data?.total+" records"}</span>
        <div><button className="secondary" disabled={page===0||pending} onClick={()=>setPage(page-1)}><ChevronLeft size={16}/> Previous</button><button className="secondary" disabled={!canAdvance||pending} onClick={()=>setPage(page+1)}>Next <ChevronRight size={16}/></button></div>
      </div>
    </section>
  </>;
}
