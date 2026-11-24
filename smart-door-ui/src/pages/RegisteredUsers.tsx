import {useState,type Dispatch,type SetStateAction} from "react";
import {Plus,Search,Trash2,UserRound,Users} from "lucide-react";
import {type Person} from "../services/demo";
import {formatDate} from "../services/supabase";

export function RegisteredUsers({demo,people,setPeople}:{demo:boolean;people:Person[];setPeople:Dispatch<SetStateAction<Person[]>>}) {
  const [search,setSearch]=useState("");
  const [adding,setAdding]=useState(false);
  const [name,setName]=useState("");
  const [remove,setRemove]=useState<Person|null>(null);
  const filtered=people.filter(person=>person.name.toLowerCase().includes(search.trim().toLowerCase()));
  return <>
    <div className="page-heading"><div><h1>Registered users</h1><p>View people enrolled for facial recognition.</p></div><button className="primary" disabled={!demo} onClick={()=>setAdding(value=>!value)}><Plus size={18}/> Add person</button></div>
    {demo?<section className="panel">
      {adding&&<form className="filters inline-form" onSubmit={event=>{event.preventDefault();if(!name.trim()) return;setPeople(value=>[...value,{id:crypto.randomUUID(),name:name.trim(),date:new Date().toISOString()}]);setName("");setAdding(false);}}>
        <label className="filter-search">Demo person name<input autoFocus required maxLength={80} value={name} onChange={event=>setName(event.target.value)}/></label><button className="primary">Add to demo roster</button><button type="button" className="secondary" onClick={()=>setAdding(false)}>Cancel</button>
      </form>}
      <div className="filters"><label className="filter-search">Person<div className="searchbox"><Search size={18}/><input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search registered users"/></div></label></div>
      {remove&&<div className="feedback" role="status">Remove {remove.name} from the demo roster? <button className="secondary danger" onClick={()=>{setPeople(value=>value.filter(person=>person.id!==remove.id));setRemove(null);}}>Confirm removal</button> <button className="secondary" onClick={()=>setRemove(null)}>Cancel</button></div>}
      {filtered.length?<ul className="roster">{filtered.map(person=><li key={person.id}><span className="table-avatar"><UserRound size={16}/></span><div><strong>{person.name}</strong><small>Enrolled {formatDate(person.date)}</small></div><button className="icon-button danger" aria-label={"Remove "+person.name} onClick={()=>setRemove(person)}><Trash2 size={18}/></button></li>)}</ul>:<p className="empty">No people match your search.</p>}
    </section>:<section className="panel empty-state"><Users size={32}/><h2>Roster unavailable from Supabase</h2><p>Enrollment is managed by the recognition program. The viewer needs a protected roster API with names and enrollment dates to list people here.</p><p>Adding and removing people requires authorized backend enrollment and removal endpoints.</p></section>}
  </>;
}
