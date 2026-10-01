// Test transcripts are opt-in on the server. Session handles never enter transcript data.
const KEY='saljari.session.v1';
let pending;
export function getSession(){
 if(!pending)pending=(async()=>{
  let token;try{const saved=JSON.parse(sessionStorage.getItem(KEY));if(Date.now()-saved.at<3500000)token=saved.token;}catch{}
  let response=await fetch('/api/bootstrap',{headers:token?{'X-Session':token}:{}});
  if(response.status===403)response=await fetch('/api/bootstrap');
  if(!response.ok)throw new Error('서버 연결을 확인해 줘.');
  const data=await response.json();try{sessionStorage.setItem(KEY,JSON.stringify({token:data.token,at:Date.now()}));}catch{}
  return data;
 })().catch(error=>{pending=null;throw error;});return pending;
}
export async function debugEvent(event,data){
 try{
  let session=await getSession();if(!session.debug_enabled)return;
  const send=()=>fetch('/api/debug-event',{method:'POST',headers:{'Content-Type':'application/json','X-Session':session.token},body:JSON.stringify({event,data})});
  const response=await send();if(response.status===403){pending=null;try{sessionStorage.removeItem(KEY);}catch{}session=await getSession();if(session.debug_enabled)await send();}
 }catch{ /* Diagnostics do not block product actions. */ }
}
