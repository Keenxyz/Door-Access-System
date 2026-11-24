import {useEffect,useState} from "react";
import {isExpired} from "./supabase";

export function useData<T>(load:()=>Promise<T>, interval=0) {
  const [version,setVersion]=useState(0);
  const [state,setState]=useState<{load:()=>Promise<T>;data?:T;error?:string;pending:boolean}>({load,pending:true});
  useEffect(()=>{
    let active=true;
    let fetching=false;
    async function refresh() {
      if(fetching) return;
      fetching=true;
      try {
        const data=await load();
        if(active) setState({load,data,pending:false});
      } catch(error) {
        if(active) setState(current=>({load,data:current.load===load?current.data:undefined,pending:false,error:isExpired(error)?"Your session expired. Sign out and sign in again.":error instanceof Error?error.message:"Unable to load data."}));
      } finally { fetching=false; }
    }
    void refresh();
    const timer=interval?window.setInterval(()=>{if(!document.hidden) void refresh();},interval):undefined;
    return ()=>{active=false;window.clearInterval(timer);};
  },[load,version,interval]);
  return {...(state.load===load?state:{data:undefined,error:undefined,pending:true}),reload:()=>{setState(current=>({...current,pending:true}));setVersion(value=>value+1);}};
}
