import type {LucideIcon} from "lucide-react";
export function StatusCard({icon:Icon,label,value,detail,tone="green"}:{icon:LucideIcon;label:string;value:string|number;detail:string;tone?:"green"|"red"|"muted"}){
 return <article className="panel stat"><div className="stat-top"><h2>{label}</h2><span className={"stat-icon "+tone}><Icon size={19}/></span></div><strong>{value}</strong><p>{detail}</p></article>;
}
