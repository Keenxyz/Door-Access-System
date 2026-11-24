import {Menu} from "lucide-react";
export function Navbar({name,demo,menuOpen,openMenu}:{name:string;demo:boolean;menuOpen:boolean;openMenu:()=>void}){
 return <header className="navbar"><div><button className="icon-button mobile-menu" aria-label="Open navigation" aria-controls="sidebar" aria-expanded={menuOpen} onClick={openMenu}><Menu size={22}/></button><span>{name}</span></div><span className={"mode-badge "+(demo?"demo":"live")}><i aria-hidden="true"/>{demo?"Demo mode":"Supabase viewer"}</span></header>;
}
