// Preference logic has no dependency on cameras or Three.js meshes.
export const STORAGE_KEY='saljari.village.v1';
export const CATEGORIES=Object.freeze([
 {id:'living',label:'생활·건강',short:'생활',color:'#e49375',angle:-150,question:'장보기와 일상에서 가까웠으면 하는 곳은?',placeholder:'큰 마트에서 자주 장을 봐. 걸어서 10분 정도면 좋겠어.'},
 {id:'transport',label:'교통·동선',short:'교통',color:'#e9bc62',angle:-90,question:'주로 어디로, 어떻게 이동해?',placeholder:'버스로 출퇴근해. 정류장이 가깝고 환승이 적으면 좋겠어.'},
 {id:'education',label:'교육·육아',short:'교육',color:'#7babc4',angle:-30,question:'학교·학원·통학에서 중요한 것은?',placeholder:'초등학생 아이가 있어. 학교와 영어 학원이 가까웠으면 해.'},
 {id:'safety',label:'안전·환경',short:'안전',color:'#9c9ac5',angle:30,question:'특히 확인하고 싶은 주변 환경은?',placeholder:'저녁에 걸어 다녀. 야간 보행과 주변 소음이 신경 쓰여.'},
 {id:'leisure',label:'여가·관계',short:'여가',color:'#87b49a',angle:90,question:'즐기는 취미나 자주 만나는 장소는?',placeholder:'탁구를 즐겨. 자유롭게 이용할 곳과 산책할 공원이 있으면 해.'},
 {id:'housing',label:'집·비용',short:'비용',color:'#ba9b7d',angle:150,question:'주거 형태·면적·예산은 어떻게 생각해?',placeholder:'아파트 전세를 생각해. 주변 실거래 수준을 참고하고 싶어.'},
]);
export const RADII=Object.freeze([2.4,3.6,4.8,6,7.2]);
export const FLOOR_LIMIT=7.9;
const ids=new Set(CATEGORIES.map(c=>c.id));
const text=(value,max)=>typeof value==='string'?value.slice(0,max):'';
export function levelForPosition(x,z){
 if(!Number.isFinite(x)||!Number.isFinite(z))throw new TypeError('finite floor coordinates required');
 const distance=Math.hypot(x,z);return 1+RADII.slice(0,-1).filter((r,i)=>distance>(r+RADII[i+1])/2).length;
}
export function rawWeight(block){return 120-20*levelForPosition(block.x,block.z);}
export function shares(blocks){
 if(!blocks.length)return {};
 const sum=blocks.reduce((n,b)=>n+rawWeight(b),0);
 const values=blocks.map(b=>({id:b.id,value:Math.floor(rawWeight(b)/sum*1000),remainder:rawWeight(b)/sum*1000%1}));
 const remaining=1000-values.reduce((n,v)=>n+v.value,0);
 values.slice().sort((a,b)=>b.remainder-a.remainder||a.id.localeCompare(b.id)).slice(0,remaining).forEach(v=>v.value++);
 return Object.fromEntries(values.map(v=>[v.id,v.value/10]));
}
export function emptyDraft(){return {version:1,entry:null,location:'',blocks:[],answers:{},focus:null,handoff:false};}
export function placement(x,z,others=[]){
 if(!Number.isFinite(x)||!Number.isFinite(z))return null;
 let radius=Math.hypot(x,z),angle=radius?Math.atan2(z,x):0;
 radius=Math.min(FLOOR_LIMIT,Math.max(RADII[0],radius));
 const candidate={x:Math.round(Math.cos(angle)*radius*2)/2,z:Math.round(Math.sin(angle)*radius*2)/2};
 const level=levelForPosition(candidate.x,candidate.z);
 function fits(p){const r=Math.hypot(p.x,p.z);return r>=2&&r<=FLOOR_LIMIT&&others.every(b=>Math.hypot(b.x-p.x,b.z-p.z)>=1.9);}
 if(fits(candidate))return candidate;
 for(let i=1;i<=30;i++)for(const direction of [-1,1]){
  const a=angle+direction*i*Math.PI/30,r=RADII[level-1];
  const p={x:Math.round(Math.cos(a)*r*2)/2,z:Math.round(Math.sin(a)*r*2)/2};
  if(levelForPosition(p.x,p.z)===level&&fits(p))return p;
 }
 return null;
}
export function toggleCategory(draft,id){
 if(!ids.has(id))return false;
 const at=draft.blocks.findIndex(b=>b.id===id);
 if(at>=0){if(draft.blocks.length===1)return false;draft.blocks.splice(at,1);if(draft.focus===id)draft.focus=draft.blocks[0]?.id||null;return true;}
 const c=CATEGORIES.find(c=>c.id===id),a=c.angle*Math.PI/180;
 const p=placement(Math.cos(a)*RADII[2],Math.sin(a)*RADII[2],draft.blocks);if(!p)return false;
 draft.blocks.push({id,...p});draft.focus=id;return true;
}
export function moveBlock(draft,id,x,z){
 const b=draft.blocks.find(b=>b.id===id);if(!b)return false;
 const p=placement(x,z,draft.blocks.filter(b=>b.id!==id));if(!p)return false;
 Object.assign(b,p);return true;
}
export function setLevel(draft,id,level){
 const b=draft.blocks.find(b=>b.id===id);if(!b||!Number.isInteger(level)||level<1||level>5)return false;
 const a=Math.atan2(b.z,b.x),r=RADII[level-1];return moveBlock(draft,id,Math.cos(a)*r,Math.sin(a)*r);
}
export function readDraft(serialized){
 try{
  const saved=JSON.parse(serialized);if(saved?.version!==1||!Array.isArray(saved.blocks))return emptyDraft();
  const draft=emptyDraft();draft.entry=['known','discover'].includes(saved.entry)?saved.entry:null;draft.location=text(saved.location,200);
  for(const b of saved.blocks.slice(0,6))if(ids.has(b?.id)&&!draft.blocks.some(v=>v.id===b.id)){
   const p=placement(b.x,b.z,draft.blocks);if(p)draft.blocks.push({id:b.id,...p});
  }
  draft.focus=draft.blocks.some(b=>b.id===saved.focus)?saved.focus:draft.blocks[0]?.id||null;
  for(const c of CATEGORIES)draft.answers[c.id]=text(saved.answers?.[c.id],450);
  draft.handoff=saved.handoff===true;return draft;
 }catch{return emptyDraft();}
}
export function buildRequest(draft){
 const summary=shares(draft.blocks);
 const lines=['진주 주거 생활권을 내 조건으로 검토해 줘.',draft.entry==='known'?'이미 생각한 후보가 있어. 위치는 지도에서 직접 지정할게.':'진주 안에서 생활권부터 탐색하고 싶어.'];
 if(draft.location.trim())lines.push('주소/동네 메모: '+draft.location.trim());
 lines.push('아래 카테고리만 선택했어. 중요도는 내가 배치해서 정한 값이며 임의 변경하지 마.');
 for(const b of draft.blocks){const c=CATEGORIES.find(c=>c.id===b.id);lines.push(`${c.label}: 중요도 ${rawWeight(b)}, 상대 비중 ${summary[b.id]}%. ${draft.answers[b.id]?.trim()||'세부 조건은 아직 모르겠어. 필요한 내용만 질문해 줘.'}`);}
 if(draft.blocks.some(b=>b.id==='housing'))lines.push('집·비용은 실거래 참고만 필요하고 가격 점수/실제 매물 추천은 제외해 줘.');
 return lines.join('\n');
}
export function applyVillagePreferences(profile,draft){
 const selected=new Map(draft.blocks.map(b=>[b.id,b]));
 const missing=draft.blocks.filter(b=>b.id!=='housing'&&(!profile.groups.some(g=>g.id===b.id)||!profile.criteria.some(c=>c.group_id===b.id&&c.importance>0))).map(b=>b.id);
 if(missing.length)return {profile:null,missing,referenceOnly:false};
 const copy=structuredClone(profile);
 copy.groups=copy.groups.filter(g=>selected.has(g.id));
 copy.criteria=copy.criteria.filter(c=>selected.has(c.group_id));
 const criterionIds=new Set(copy.criteria.map(c=>c.id));
 copy.questions=copy.questions.filter(q=>!q.criterion_ids.length||q.criterion_ids.some(id=>criterionIds.has(id))).map(q=>({...q,criterion_ids:q.criterion_ids.filter(id=>criterionIds.has(id))}));
 for(const g of copy.groups){g.weight=g.id==='housing'?0:selected.has(g.id)?rawWeight(selected.get(g.id)):0;g.source='user';g.reason=g.id==='housing'?'집·비용은 실거래 참고만':'블록 마을에서 선택한 중요도';}
 if(!copy.groups.some(g=>g.weight>0))return {profile:null,missing:[],referenceOnly:true};
 return {profile:copy,missing:[],referenceOnly:false};
}
