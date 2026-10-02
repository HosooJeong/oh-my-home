export function readCandidates(value){
 const out=[];
 for(const p of Array.isArray(value)?value.slice(0,6):[]){
  if(typeof p?.id!=='string'||!/^[a-z][a-z0-9_-]{0,63}$/.test(p.id)||typeof p.label!=='string'||!p.label.trim()||!Number.isFinite(p.latitude)||!Number.isFinite(p.longitude)||Math.abs(p.latitude)>90||Math.abs(p.longitude)>180)continue;
  if(out.some(x=>x.id===p.id||samePlace(x,p)))continue;
  out.push({id:p.id,label:p.label.slice(0,200),latitude:p.latitude,longitude:p.longitude,origin:'user'});
 }
 return out;
}
export function samePlace(a,b){return Math.abs(a.latitude-b.latitude)<.00001&&Math.abs(a.longitude-b.longitude)<.00001;}
export function entryReady(draft){const count=readCandidates(draft.candidates).length;return draft.entry==='discover'||(draft.entry==='single'?count===1:draft.entry==='multiple'&&count>=2&&count<=6);}
export function addCandidate(draft,place){
 const next=readCandidates([place])[0];if(!next)throw new Error('집 위치를 확인해 주세요.');
 if(draft.candidates.some(p=>samePlace(p,next)))throw new Error('이미 선택한 집이에요.');
 if(draft.entry==='single')draft.candidates=[next];
 else{if(draft.candidates.length>=6)throw new Error('최대 6곳까지 비교할 수 있어요.');draft.candidates.push(next);}
 draft.handoff=false;
}
