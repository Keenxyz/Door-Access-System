import {useState,type FormEvent} from "react";
import {ArrowRight, LockKeyhole, Eye, EyeOff, ScanFace, ShieldCheck} from "lucide-react";
import {config,signIn,type Session} from "../services/supabase";
export default function Login({onSignIn,onDemo}:{onSignIn:(session:Session)=>void;onDemo:()=>void}) {
  const [show,setShow]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState("");
  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(busy)return;
    const form=new FormData(event.currentTarget);setBusy(true);setError("");
    try {onSignIn(await signIn(String(form.get("email")).trim(),String(form.get("password"))));}
    catch(e){setError(e instanceof Error && e.name==="Error"?e.message:"Could not reach Supabase. Try again.");}
    finally{setBusy(false);}
  }
  return <main className="login"><section className="login-intro">
    <div className="brand"><span className="brand-icon"><ShieldCheck size={23}/></span><span>Smart Door <small>Security</small></span></div>
    <div className="login-art" aria-hidden="true"><div className="art-grid"><ScanFace size={104} strokeWidth={1.1}/></div></div>
    <div><h1>See who’s at<br/>your door.</h1><p>Review access attempts and security alerts from one dashboard.</p></div>
  </section><section className="login-form"><div><span className="login-lock"><LockKeyhole size={22}/></span>
    <h2>Sign in</h2><p className="muted">Use your paired Supabase viewer account.</p>
    <form onSubmit={submit}>
      <label>Email address<input name="email" type="email" placeholder="you@example.com" autoComplete="username" required/></label>
      <label>Password<div className="password"><input name="password" type={show?"text":"password"} autoComplete="current-password" placeholder="Enter your password" required/><button type="button" className="icon-button" aria-label={show?"Hide password":"Show password"} onClick={()=>setShow(!show)}>{show?<EyeOff size={19}/>:<Eye size={19}/>}</button></div></label>
      {error&&<p role="alert" className="notice error">{error}</p>}
      {!config&&<p className="notice">Supabase isn’t configured. You can still explore the demo.</p>}
      <button className="button primary" disabled={busy||!config} type="submit">{busy?"Signing in…":"Sign in"}<ArrowRight size={17}/></button>
    </form>
    <button className="button secondary demo-button" type="button" disabled={busy} onClick={onDemo}>Open demo dashboard</button>
    <p className="muted demo-help">The demo uses sample records and never connects to your door.</p>
  </div></section></main>;
}
