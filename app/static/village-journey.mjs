// Visual states follow actual task boundaries, never a timer-based percentage.
export const STATUS_LABELS={unselected:'선택 안 함',reading:'조건 정리',waiting:'대기',running:'진행 중',completed:'완료',partial:'일부 미확인',failed:'실패',cancelled:'취소',not_executed:'미실행'};
const severity={completed:0,partial:1,not_executed:2,cancelled:3,failed:4,waiting:5,running:6};
export function selectedStates(ids,status='waiting'){return Object.fromEntries(ids.map(id=>[id,status]));}
export function eventStates(ids,events=[]){
 const states=selectedStates(ids),warnings={};
 for(const e of events){if(!e.module_id)continue;
  if(e.stage==='module_started'||e.stage==='reference_started')states[e.module_id]='running';
  if(e.stage==='module_finished'){states[e.module_id]=e.status==='completed'?'completed':e.status==='failed'?'failed':e.status==='cancelled'?'cancelled':'partial';if(states[e.module_id]!=='completed')warnings[e.module_id]=states[e.module_id];}
  if(e.stage==='reference_finished')states[e.module_id]=warnings[e.module_id]||(['available','empty','completed'].includes(e.status)?'completed':'partial');
  if(e.stage==='reference_failed')states[e.module_id]='failed';
 }return states;
}
function merge(a,b){if(b==='not_executed'&&a!=='not_executed')return a==='completed'?'partial':a;return severity[b]>severity[a]?b:a;}
export function resultStates(ids,run,requests=[]){
 const states=selectedStates(ids,'not_executed');
 for(const m of run?.modules||[])states[m.module_id]=m.status==='completed'?'completed':m.status==='failed'?'failed':'partial';
 for(const r of run?.references||[]){const value=['available','empty','completed'].includes(r.status)?'completed':'partial';states[r.module_id]=states[r.module_id]==='not_executed'?value:merge(states[r.module_id],value);}
 for(const a of run?.report?.assessments||[])for(const d of a.details||[])if(d.status==='unknown'){
  const m=run.profile?.criteria?.find(c=>c.id===d.criterion_id)?.module_id;
  if(m&&states[m]==='completed')states[m]='partial';
 }
 for(const r of requests){let value=r.status==='queued'?'waiting':r.status;
  if(value==='completed'&&(r.reason||r.evidence_status&&r.evidence_status!=='found'))value='partial';
  if(value in severity)states[r.module]=states[r.module]==='not_executed'?value:merge(states[r.module],value);
 }return states;
}
