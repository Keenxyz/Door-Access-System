import type { Event, Query } from "./supabase";
export type Person = { id: string; name: string; date: string };
export const demoPeople = ["Avery Cruz","Jamie Reyes","Morgan Santos","Riley Flores","Alex Rivera","Casey Lim","Taylor Garcia","Jordan Ramos"].map((name,i)=>({id:String(i),name,date:new Date(Date.now()-(i+2)*86400000).toISOString()}));
const daily = [8,13,10,16,12,18,9];
export const demoEvents: Event[] = daily.flatMap((length, day) =>
  Array.from({length},(_,index): Event=>{
    const denied = (index + day*2) % 5 === 0;
    const date = new Date();
    if(day !== 6) { date.setDate(date.getDate()-(6-day)); date.setHours(8+index%11,index*7%60,0,0); }
    else date.setMinutes(date.getMinutes()-index*7-3);
    return {id:day+"-"+index,device_id:"demo-device",occurred_at:date.toISOString(),
      person:denied?"UNKNOWN":demoPeople[(index+day)%demoPeople.length].name,result:denied?"DENIED":"GRANTED",
      similarity:denied?0.18+(index%8)*0.018:0.54+(index%8)*0.035};
  })).sort((a,b)=>b.occurred_at.localeCompare(a.occurred_at));
export function demoPage(query: Query) {
  const term=query.search?.trim().toLowerCase();
  const rows=demoEvents.filter(row=>(!query.result||row.result===query.result)&&(!term||row.person.toLowerCase().includes(term)||(row.person==="UNKNOWN"&&"unknown visitor".includes(term))));
  return {rows:rows.slice(query.page*query.size,(query.page+1)*query.size),total:rows.length};
}
