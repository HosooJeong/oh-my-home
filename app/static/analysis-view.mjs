// Read-only presentation from the reviewed profile and source-bound comparison.
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const pct=value=>(value*100).toFixed(1)+'%';
export function profileWeights(profile){
 const total=profile.groups.reduce((sum,g)=>sum+g.weight,0),result={};
 for(const g of profile.groups){const members=profile.criteria.filter(c=>c.group_id===g.id),sum=members.reduce((s,c)=>s+c.importance,0);for(const c of members)result[c.id]=total&&sum?g.weight/total*c.importance/sum:0;}
 return result;
}
export function measure(value,unit){
 if(!finite(value))return '미확인';
 if(unit==='m')return Math.round(value).toLocaleString('ko-KR')+'m · 직선거리';
 if(unit==='count')return value.toLocaleString('ko-KR')+'개소 · 등록자료';
 if(unit==='bool')return '조건 확인';
 if(unit.startsWith('KRW'))return (value/10000).toLocaleString('ko-KR')+'만원'+({'KRW/month':'/월','KRW/m2':'/㎡'}[unit]||'');
 if(unit==='m2')return value.toLocaleString('ko-KR')+'㎡';
 return value.toLocaleString('ko-KR')+' '+unit;
}
export function hardLabel(criterion){
 if(!criterion.hard)return null;
 if(criterion.utility?.unit==='bool')return '필수 · 충족 여부 확인 필요';
 const unit=criterion.utility?.unit||'',value=criterion.hard.value;
 const text=unit==='m'?value.toLocaleString('ko-KR')+'m':measure(value,unit);
 return '필수 · '+text+' '+({lte:'이하',gte:'이상',eq:'일치'}[criterion.hard.operator]||'확인 필요');
}
export function proposedComparison(criterion){
 const p=criterion.comparison_proposal,u=criterion.utility;
 return !!(p&&u&&!criterion.hard&&['direction','ideal','limit','unit'].every(k=>p.utility[k]===u[k])&&(p.radius_m===null||Number(criterion.parameters?.radius_m)===p.radius_m));
}
export function utilityLabel(criterion,detailed=false){
 if(criterion.module_id==='housing')return '집별 가격·예산 충족은 미확인';
 const u=criterion.utility;if(!u||u.unit==='bool')return '현재 정량 근거 미확인';
 const proposed=proposedComparison(criterion);
 if(proposed&&!detailed)return criterion.comparison_proposal.label+' · 비교 기준 제안';
 const value=n=>measure(n,u.unit).replace(' · 직선거리','').replace(' · 등록자료',''),prefix=(proposed?'서비스 제안 · ':'')+(u.unit==='m'?'직선거리 ':u.unit==='count'?'등록 개소 ':'');
 if(u.direction==='target')return '목표 '+value(u.ideal)+' · 목표에서 '+value(u.limit)+' 차이면 점수 없음';
 return prefix+'목표 '+value(u.ideal)+' · '+value(u.limit)+(u.direction==='lower'?' 이상':' 이하')+'이면 점수 없음'+(proposed&&criterion.comparison_proposal.radius_m!==null?' · 조회 직선반경 '+Math.round(criterion.comparison_proposal.radius_m).toLocaleString('ko-KR')+'m':'');
}
export function profileView(profile){
 const weights=profileWeights(profile),total=profile.groups.reduce((sum,g)=>sum+g.weight,0);
 return {groups:profile.groups.filter(g=>g.weight>0||g.id==='housing'||profile.criteria.some(c=>c.group_id===g.id&&c.hard)).map(g=>({
  ...g,share:total?g.weight/total:0,criteria:profile.criteria.filter(c=>c.group_id===g.id&&(weights[c.id]>0||c.hard)).map(c=>({
   ...c,weight:weights[c.id],share:pct(weights[c.id]),hardLabel:hardLabel(c),rule:utilityLabel(c),ruleDetail:proposedComparison(c)?utilityLabel(c,true):null}))})),
  excluded:profile.criteria.filter(c=>weights[c.id]===0&&!c.hard),pendingQuestions:profile.questions};
}
export function confirmReviewedProfile(profile,snapshot){
 if(snapshot!==undefined&&JSON.stringify(profile)!==snapshot)throw new Error('확인할 조건이 바뀌었어요. 다시 확인해 주세요.');
 if(profile.questions.some(q=>q.blocking))throw new Error('필요한 답변을 먼저 입력해 주세요.');
 const copy=structuredClone(profile),view=profileView(profile),groups=new Set(view.groups.map(g=>g.id)),criteria=new Set(view.groups.flatMap(g=>g.criteria.map(c=>c.id)));
 copy.revision++;for(const g of copy.groups)if(groups.has(g.id))g.source='user';
 // Accepting the proposal enables ranking; keep its original proposed value separately.
 for(const c of copy.criteria)if(criteria.has(c.id)){if(c.importance_source==='proposed')c.importance_proposal=c.importance;c.source='user';c.importance_source='user';}
 // Unanswered optional questions stay visible; confirming conditions is not an interview answer.
 return copy;
}
export function housingQueryProfile(profile){
 // A reference lookup uses context filters, never verdicts on criteria or interview answers.
 if(profile.groups.some(g=>g.weight>0))return profile;
 const copy=structuredClone(profile);copy.groups=copy.groups.filter(g=>g.id==='housing');
 if(!copy.groups.length)throw new Error('실거래 참고 범위를 확인해 주세요.');
 copy.criteria=[];copy.questions=[];
 if(!copy.context.some(c=>c.key==='housing_reference'&&c.value==='requested'))copy.context.push({key:'housing_reference',value:'requested',source_quote:profile.request.slice(0,500)});
 return copy;
}
function fit(value,u){
 if(u.direction==='boolean')return Number(value===u.ideal);
 const score=u.direction==='target'?1-Math.abs(value-u.ideal)/u.limit:(value-u.limit)/(u.ideal-u.limit);
 return Math.max(0,Math.min(1,score));
}
export function candidateViews(profile,run,places){
 const weights=profileWeights(profile),facts=new Map((run.modules||[]).flatMap(m=>m.evidence).map(e=>[e.id,e]));
 const views=places.map(p=>{
  const a=run.report.assessments.find(a=>a.candidate_id===p.id);if(!a)return null;
  const rows=a.details.filter(d=>d.status!=='not_requested').map(d=>{
   const c=profile.criteria.find(c=>c.id===d.criterion_id);if(!c)return null;
   const e=facts.get(d.evidence_id),module=run.modules.find(m=>m.module_id===c.module_id);
   const bound=e?.candidate_id===p.id&&e?.criterion_id===c.id;
   const validWeight=finite(d.weight)&&Math.abs(d.weight-weights[c.id])<1e-9;
   const known=d.status==='known'&&bound&&validWeight&&e.status==='verified'&&finite(e.value)&&c.utility&&e.unit===c.utility.unit;
   const reason=!validWeight||e&&!bound?'결과 연결 확인 필요':e?.status==='conflicting'?'자료 충돌':module?.status==='failed'?'조회 실패':module?.unsupported_criterion_ids?.includes(c.id)?'현재 정량 평가 미지원':'자료 미확인';
   const education=run.education_details?.find(x=>x.candidate_id===p.id&&x.criterion_id===c.id);
   const leisure=run.leisure_details?.find(x=>x.candidate_id===p.id&&x.criterion_id===c.id);
   const nearest=bound&&run.facilities?.[e.source_record];
   const facilities=[...(nearest?[nearest]:[]),...(education?.selected||[]),...(leisure?.selected||[]),...(leisure?.registered_leads||[])];
   return {criterion:c,weight:weights[c.id],known:!!known,fact:bound?e:null,reason,fit:known?fit(e.value,c.utility):null,
    contribution:known?100*weights[c.id]*fit(e.value,c.utility):null,hardStatus:d.hard_status,
    measure:known?measure(e.value,e.unit):reason,facilities:[...new Map(facilities.map(f=>[f.id,f])).values()],
    scopeNote:education?.note||leisure?.note,registeredLeads:!!leisure?.registered_leads};
  }).filter(Boolean);
  return {place:p,assessment:a,rows,hardFailed:rows.filter(r=>r.hardStatus==='fail'),hardUnknown:rows.filter(r=>r.hardStatus==='unknown'),unknown:rows.filter(r=>!r.known),comparisons:[]};
 }).filter(Boolean);
 for(const view of views){
  const differences=[];let shared=0;
  for(const row of view.rows.filter(r=>r.known&&r.weight>0))for(const other of views.filter(v=>v!==view&&v.assessment.eligibility!=='ineligible')){
   const peer=other.rows.find(r=>r.criterion.id===row.criterion.id&&r.known);if(!peer)continue;
   shared++;const gap=(row.fit-peer.fit)*row.weight;if(Math.abs(gap)<1e-9)continue;
   differences.push({gap,text:`${row.criterion.label}: ${other.place.label}보다 내 기준에서 ${gap>0?'유리':'불리'}해요 (${row.measure}, 비교 ${peer.measure})`,criterionId:row.criterion.id,peerId:other.place.id});
  }
  const good=differences.filter(x=>x.gap>0).sort((a,b)=>b.gap-a.gap),bad=differences.filter(x=>x.gap<0).sort((a,b)=>a.gap-b.gap);
  view.comparisons=[good[0],bad[0]].filter(Boolean);
  view.comparisonNote=views.length===1?'한 곳 분석 · 후보 간 비교 없음':view.assessment.eligibility==='ineligible'?'필수조건 미충족 · 추천 순위 제외':shared?'공통 조건의 평가값 차이 없음':'후보 비교 근거 부족';
  if(view.assessment.eligibility==='ineligible')view.comparisons=[];
 }
 return views;
}
export function researchCounts(requests){
 const counts={related:0,no_quote:0,unknown:0,not_executed:0,failed:0,cancelled:0,pending:0};
 for(const r of requests){if(r.status==='not_executed')counts.not_executed++;else if(r.status==='failed')counts.failed++;else if(r.status==='cancelled')counts.cancelled++;else if(['queued','running'].includes(r.status))counts.pending++;else if(r.status==='completed'&&r.evidence_status==='found')counts.related++;else if(r.status==='completed'&&r.evidence_status==='not_found')counts.no_quote++;else counts.unknown++;}
 return counts;
}
