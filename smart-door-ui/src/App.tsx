import {useEffect,useState} from "react";
import {Navigate,Route,Routes,useLocation,useNavigate} from "react-router-dom";
import {Navbar} from "./components/Navbar";
import {Sidebar} from "./components/Sidebar";
import Login from "./pages/Login";
import {Dashboard} from "./pages/Dashboard";
import {AccessLogs} from "./pages/AccessLogs";
import {RegisteredUsers} from "./pages/RegisteredUsers";
import {Notifications} from "./pages/Notifications";
import {Settings} from "./pages/Settings";
import {demoPeople} from "./services/demo";
import type {Session} from "./services/supabase";

import {readPreference,writePreference,type Theme} from "./services/preferences";

export default function App(){
  const [session,setSession]=useState<Session|null>(null);
  const [demo,setDemo]=useState(false);
  const [people,setPeople]=useState(demoPeople);
  const [menu,setMenu]=useState(false);
  const [theme,setTheme]=useState<Theme>(()=>readPreference("theme","system"));
  const location=useLocation();
  const navigate=useNavigate();
  useEffect(()=>{document.documentElement.dataset.theme=theme;writePreference("theme",theme);},[theme]);
  useEffect(()=>{
    if(!menu) return;
    const close=(event:KeyboardEvent)=>{if(event.key==="Escape") setMenu(false);};
    window.addEventListener("keydown",close);
    return ()=>window.removeEventListener("keydown",close);
  },[menu]);

  if(!demo&&!session) return <Login onSignIn={setSession} onDemo={()=>{setDemo(true);navigate("/");}}/>;
  function signOut(){setSession(null);setDemo(false);setPeople(demoPeople);setMenu(false);navigate("/");}
  const identity=demo?"demo":session?.id??"";
  const paths:Record<string,string>={"/":"Overview","/logs":"Access logs","/people":"Registered users","/alerts":"Notifications","/settings":"Settings"};

  return <div className="app-layout">
    <a className="skip-link" href="#main-content" onClick={event=>{event.preventDefault();document.getElementById("main-content")?.focus();}}>Skip to content</a>
    <Sidebar open={menu} onClose={()=>setMenu(false)} email={session?.email??""} onSignOut={signOut}/>
    <div className="app-body"><Navbar name={paths[location.pathname]??"Smart Door Security"} demo={demo} menuOpen={menu} openMenu={()=>setMenu(value=>!value)}/>
      <main className="page-content" id="main-content" tabIndex={-1}>
        {demo&&<p className="demo-banner">Demo mode · Sample data and simulated device status</p>}
        <Routes>
          <Route path="/" element={<Dashboard session={session} demo={demo} userCount={people.length}/>}/>
          <Route path="/logs" element={<AccessLogs session={session}/>}/>
          <Route path="/people" element={<RegisteredUsers demo={demo} people={people} setPeople={setPeople}/>}/>
          <Route path="/alerts" element={<Notifications key={identity} session={session} identity={identity}/>}/>
          <Route path="/settings" element={<Settings key={identity} session={session} identity={identity} theme={theme} setTheme={setTheme} onSignOut={signOut}/>}/>
          <Route path="*" element={<Navigate to="/" replace/>}/>
        </Routes>
      </main>
    </div>
  </div>;
}
