export function Feedback({pending,error,reload}:{pending:boolean;error?:string;reload:()=>void}) {
  return <>{pending&&<p role="status" className="feedback">Loading…</p>}{error&&<div className="feedback error" role="alert">{error} <button className="secondary" onClick={reload}>Retry</button></div>}</>;
}
