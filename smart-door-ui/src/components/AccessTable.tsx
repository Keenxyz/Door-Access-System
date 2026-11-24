import {CircleCheck,CircleX,ScanFace} from "lucide-react";
import {displayName,eventKey,formatDate,type Event} from "../services/supabase";
export function DecisionBadge({result}:{result:Event["result"]}) {const granted=result==="GRANTED";const Icon=granted?CircleCheck:CircleX;return <span className={"badge "+(granted?"green":"red")}><Icon size={14}/>{granted?"Granted":"Denied"}</span>}
export function AccessTable({rows}:{rows:Event[]}) {
 if(!rows.length)return <div className="empty"><ScanFace size={26}/><strong>No access records</strong><span>Try a different filter or wait for a scan to upload.</span></div>;
 return <div className="table-wrap"><table><thead><tr><th scope="col">Person</th><th scope="col">Decision</th><th scope="col">Date and time</th><th scope="col">Similarity</th></tr></thead><tbody>{rows.map(row=><tr key={eventKey(row)}><td data-label="Person"><span className={"table-avatar "+(row.result==="DENIED"?"red":"green")}><ScanFace size={16}/></span>{displayName(row)}</td><td data-label="Decision"><DecisionBadge result={row.result}/></td><td data-label="Date and time">{formatDate(row.occurred_at)}</td><td data-label="Similarity" className="score">{row.similarity.toFixed(3)}</td></tr>)}</tbody></table></div>;
}
