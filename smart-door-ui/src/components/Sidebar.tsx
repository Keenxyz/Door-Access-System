import {Activity,Bell,LayoutDashboard,LogOut,Settings,ShieldCheck,Users,X} from "lucide-react";
import {NavLink} from "react-router-dom";
const links=[["/","Overview",LayoutDashboard],["/logs","Access logs",Activity],["/people","Registered users",Users],["/alerts","Notifications",Bell],["/settings","Settings",Settings]] as const;
export function Sidebar({open,onClose,email,onSignOut}:{open:boolean;onClose:()=>void;email:string;onSignOut:()=>void}){
 return <><button type="button" className="scrim" aria-label="Close navigation" hidden={!open} onClick={onClose}/><aside id="sidebar" className={"sidebar"+(open?" open":"")}><div className="side-head">
 <NavLink to="/" className="brand" onClick={onClose}><span className="brand-icon"><ShieldCheck size={23}/></span><span>Smart Door <small>Security</small></span></NavLink><button type="button" className="icon-button mobile-close" aria-label="Close menu" onClick={onClose}><X/></button></div>
 <nav aria-label="Main menu">{links.map(([to,name,Icon])=><NavLink end={to==="/"} key={to} to={to} onClick={onClose}><Icon size={19}/>{name}</NavLink>)}</nav>
 <div className="side-bottom"><span className="profile-icon">{(email[0]||"D").toUpperCase()}</span><div><strong>{email?"Viewer account":"Demo workspace"}</strong><small>{email||"Sample data"}</small></div><button type="button" className="icon-button sign-out" aria-label={email?"Sign out":"Exit demo"} onClick={onSignOut}><LogOut size={18}/></button></div>
 </aside></>;
}
