import {CATEGORIES} from './village-model.mjs';
import {utilityLabel,hardLabel,profileWeights,measure} from './analysis-view.mjs';
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const valid=r=>r.known&&finite(r.fit)&&r.fit>=0&&r.fit<=1;
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
export const percentage=n=>finite(n)?n.toFixed(1).replace(/\.0$/,'')+'%':'미확인';
export function criterionReason(row){
 if(!valid(row))return row.reason+'이라 목표 충족 여부를 판단할 수 없어.';
 if(row.fit===1)return '네가 정한 목표 수준을 충족해.';
 const u=row.criterion.utility,value=row.fact?.value;
 if(u?.direction==='boolean')return '확인된 값이 네가 원하는 조건과 일치하지 않아.';
 if(!u||!finite(value))return '확인한 조건이 네 목표에는 미치지 못해.';
 const difference=measure(Math.abs(value-u.ideal),u.unit).replace(' · 직선거리','').replace(' · 등록자료','');
 if(u.direction==='target')return '원하는 수준과 '+difference+' 차이가 있어.';
 return '목표보다 '+difference+(u.direction==='higher'?' 적어.':u.unit==='m'?' 더 멀어.':' 높아.');
}

// Fulfilment uses the person's utility curve. Priority weights are not target levels.
export function categoryReports(profile,view,selected=[]){
 const weights=profileWeights(profile),groupTotal=profile.groups.reduce((n,g)=>n+g.weight,0);
 const categories=[...CATEGORIES,...profile.groups.filter(g=>!CATEGORIES.some(c=>c.id===g.id)).map(g=>({...g,short:g.label,color:'#738079'}))];
 return categories.map(c=>{
  const group=profile.groups.find(g=>g.id===c.id),rows=(view?.rows||profile.criteria.filter(r=>r.hard).map(criterion=>({criterion,weight:weights[criterion.id],known:false,fit:null,reason:'집별 조건 미확인',hardStatus:'unknown',facilities:[]}))).filter(r=>r.criterion.group_id===c.id);
  const requested=selected.includes(c.id)||!!group&&(group.weight>0||profile.criteria.some(r=>r.group_id===c.id&&r.hard));
  const scored=rows.filter(r=>r.weight>0),total=scored.reduce((n,r)=>n+r.weight,0),known=scored.filter(valid),coverage=total?known.reduce((n,r)=>n+r.weight,0)/total:null;
  const lower=total?100*known.reduce((n,r)=>n+r.weight*r.fit,0)/total:null;
  const hardUnknown=rows.some(r=>r.criterion.hard&&r.hardStatus==='unknown'),complete=total>0&&scored.every(valid)&&!hardUnknown;
  const target=requested&&c.id!=='housing'&&profile.criteria.some(r=>r.group_id===c.id&&weights[r.id]>0)?100:null;
  const score=target!==null&&complete?lower:null,range=target!==null&&total?[lower,Math.min(100,lower+100*(1-coverage))]:null;
  const status=!requested?'unselected':c.id==='housing'?'reference':score!==null?'known':known.length?'partial':'unknown';
  return {...c,requested,rows,target,score,range,coverage,status,share:groupTotal?(group?.weight||0)/groupTotal:0,
   hardFailed:rows.filter(r=>r.hardStatus==='fail'),hardUnknown:rows.filter(r=>r.hardStatus==='unknown')};
 });
}

// Missing axes stay open. A verified zero is a real point at the centre.
export function radarGeometry(categories){
 const axes=CATEGORIES.map(c=>categories.find(a=>a.id===c.id)||{...c,target:null,score:null,status:'unselected'});
 const point=(i,value)=>{const angle=-Math.PI/2+i*Math.PI/3,r=122*value/100;return [220+Math.cos(angle)*r,202+Math.sin(angle)*r];};
 const segments=key=>axes.flatMap((a,i)=>{const j=(i+1)%6;return finite(a[key])&&finite(axes[j][key])?[[point(i,a[key]),point(j,axes[j][key])]]:[];});
 return {axes,point,target:segments('target'),actual:segments('score'),complete:axes.every(a=>finite(a.score))};
}
export function researchNotes(data,requests,category='overview'){
 if(!data)return [];
 const ids=new Set(requests.filter(r=>category==='overview'||r.module===category).map(r=>r.id)),notes=[];
 const include=x=>category==='overview'||(x.request_ids||[]).some(id=>ids.has(id));
 for(const item of data.items||[])for(const x of item.excerpts||[])if(include(x))notes.push({kind:'facility',facilityId:item.facility_id,excerpt:x});
 for(const item of data.safety?.items||[])for(const x of item.excerpts||[])if((category==='overview'||category==='safety')&&include(x))notes.push({kind:'area',title:item.area_name,excerpt:x,scope:'지역 공식 자료 · 이 집에 대한 개별 안전 판정은 아니야.'});
 for(const item of data.leisure?.discoveries||[]){
  const matching=category==='overview'||category==='leisure'&&requests.some(r=>r.module==='leisure'&&r.criterion_ids?.includes(item.criterion_id));
  for(const x of item.excerpts||[])if((category==='overview'||category==='leisure')&&include(x))notes.push({kind:'discovery',title:item.name,excerpt:x,role:item.role_label,scope:'시설 발견 참고 · 이 집에서의 거리·이용 가능성은 미확인이야.'});
  if(matching&&!item.excerpts?.length)notes.push({kind:'discovery',title:item.name,note:item.note,url:item.source_url,scope:'시설 후보 · 조건 충족 근거는 미확인이야.'});
 }
 return notes;
}
export function renderRadar(root,categories){
 const ns='http://www.w3.org/2000/svg',shape=(tag,attrs)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e;};
 const geo=radarGeometry(categories),svg=shape('svg',{viewBox:'0 0 440 416',role:'img'});
 svg.setAttribute('aria-label',geo.axes.map(a=>`${a.label}: ${a.target===null?'목표 미설정':'목표 100'}, ${a.score!==null?'확인된 충족도 '+percentage(a.score):a.status==='reference'?'실거래 참고':a.status==='unselected'?'미선택':'충족도 미확인'}`).join(' · '));
 const title=shape('title',{});title.textContent='내 목표와 확인된 조건 충족도';svg.append(title);
 for(const value of [25,50,75,100])svg.append(shape('polygon',{points:geo.axes.map((_,i)=>geo.point(i,value).join(',')).join(' '),class:'radar-grid'}));
 geo.axes.forEach((a,i)=>{const p=geo.point(i,100);svg.append(shape('line',{x1:220,y1:202,x2:p[0],y2:p[1],class:'radar-axis'}));});
 for(const [name,segments] of [['target',geo.target],['actual',geo.actual]])for(const [a,b] of segments)svg.append(shape('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'radar-'+name}));
 if(geo.complete)svg.append(shape('polygon',{points:geo.axes.map((a,i)=>geo.point(i,a.score).join(',')).join(' '),class:'radar-area'}));
 geo.axes.forEach((a,i)=>{
  if(a.target!==null){const p=geo.point(i,a.target);svg.append(shape('circle',{cx:p[0],cy:p[1],r:4,class:'radar-target-point'}));}
  if(a.score!==null){const p=geo.point(i,a.score);svg.append(shape('circle',{cx:p[0],cy:p[1],r:5,class:'radar-actual-point'}));}
  else if(a.range&&a.range[1]-a.range[0]>1e-8){const p=geo.point(i,a.range[0]),q=geo.point(i,a.range[1]);svg.append(shape('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],class:'radar-unknown-range'}));}
  const p=geo.point(i,138),label=shape('text',{x:p[0],y:p[1]-2,'text-anchor':'middle',class:'radar-label'+(!a.requested?' muted':'')});label.textContent=a.short;svg.append(label);
  const value=shape('text',{x:p[0],y:p[1]+19,'text-anchor':'middle',class:'radar-value'});value.textContent=a.score!==null?percentage(a.score):{reference:'참고',unselected:'미선택',partial:'일부 미확인',unknown:'미확인'}[a.status];svg.append(value);
 });
 const legend=node('div',undefined,'radar-legend');legend.append(node('span','내 목표','target'),node('span','확인된 충족도','actual'));if(geo.axes.some(a=>a.target!==null&&a.score===null))legend.append(node('span','미확인 범위','unknown'));
 root.replaceChildren(svg,...(geo.axes.some(a=>a.target!==null)?[legend]:[]),node('figcaption',geo.axes.some(a=>a.target!==null)?'각자 정한 목표를 100으로 맞췄어. 미확인 축은 연결하지 않아.':'실거래는 참고 자료야. 집별 충족도는 수치로 판정하지 않아.','quiet'));
}

function scoreText(c){return c.score!==null?'목표 대비 '+percentage(c.score):c.status==='reference'?'가격은 참고로만 확인해':c.status==='unselected'?'이번 분석에서 선택하지 않았어':c.range&&c.coverage>0?'일부 미확인 · 가능한 충족도 '+percentage(c.range[0])+'–'+percentage(c.range[1]):'목표 충족 여부 미확인';}
export function renderReport({tabs,content,categories,view,profile,active='overview',onSelect,renderEvidence,appendSafety,selectionReason,extras}){
 const choices=[{id:'overview',short:'총평',color:'#276b51'},...categories];tabs.replaceChildren();
 choices.forEach((c,i)=>{const b=node('button',c.short,'report-tab');b.type='button';b.id='report-tab-'+c.id;b.dataset.category=c.id;b.style.setProperty('--brick-color',c.color);b.setAttribute('role','tab');b.setAttribute('aria-selected',String(c.id===active));b.setAttribute('aria-controls','report-content');b.tabIndex=c.id===active?0:-1;b.addEventListener('click',()=>onSelect(c.id,true));b.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(i+1)%choices.length;else if(event.key==='ArrowLeft')next=(i+choices.length-1)%choices.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=choices.length-1;else return;event.preventDefault();onSelect(choices[next].id,true);});tabs.append(b);});
 content.replaceChildren();content.setAttribute('aria-labelledby','report-tab-'+active);
 if(active==='overview'){
  content.append(node('h3','총평'));
  if(!view){content.append(node('p','집별 충족도는 평가하지 않았어. 요청한 실거래 자료를 참고할 수 있어.','report-lead'));extras?.(content,active);return;}
  const a=view.assessment;
  content.append(node('p',a.score===null?`원래 비중의 ${percentage(a.coverage*100)}를 확인했어. 남은 조건이 있어 전체 순위는 보류해.`:`네 조건에 대한 충족도는 ${percentage(a.score)}야.`, 'report-lead'));
  if(view.hardFailed.length)content.append(node('p','필수조건 미충족: '+view.hardFailed.map(r=>r.criterion.label).join(' · '),'hard-note'));
  if(view.hardUnknown.length)content.append(node('p','필수조건 미확인: '+view.hardUnknown.map(r=>r.criterion.label).join(' · '),'hard-note'));
  const known=categories.filter(c=>c.score!==null).sort((a,b)=>b.score-a.score),good=known.filter(c=>c.score>=80).slice(0,2),attention=[...known.filter(c=>c.score<80).reverse().slice(0,2),...categories.filter(c=>c.requested&&['partial','unknown'].includes(c.status)).slice(0,2)];
  for(const [label,items] of [['목표에 가까운 분야',good],['더 살펴볼 분야',attention]])if(items.length){const block=node('div',undefined,'report-highlights');block.append(node('h4',label));for(const c of items){const b=node('button',c.label+' · '+scoreText(c),'report-jump');b.type='button';b.addEventListener('click',()=>onSelect(c.id,true));block.append(b);}content.append(block);}
  for(const comparison of view.comparisons)content.append(node('p',comparison.text,'quiet'));if(!view.comparisons.length)content.append(node('p',view.comparisonNote,'quiet'));
  if(selectionReason)content.append(node('p',selectionReason,'quiet'));extras?.(content,active);return;
 }
 const c=categories.find(c=>c.id===active);if(!c)return;
 content.append(node('h3',c.label),node('p',scoreText(c),'report-lead'));
 if(c.requested&&c.id!=='housing')content.append(node('p','전체 반영 비중 '+percentage(c.share*100)+(c.coverage!==null?' · 이 분야에서 확인한 비중 '+percentage(c.coverage*100):''),'quiet'));
 if(!c.requested){extras?.(content,active);return;}
 if(!c.rows.length&&c.id!=='housing')content.append(node('p','이 분야의 수치 평가 조건은 아직 없어. 조사 자료가 있으면 아래에서 참고할 수 있어.','quiet'));
 for(const row of c.rows){
  const box=node('article',undefined,'report-condition');box.append(node('h4',row.criterion.label),node('p',valid(row)?row.measure:row.reason,'report-measure'),node('p',criterionReason(row)),node('p',utilityLabel(row.criterion),'quiet'));
  if(valid(row)&&c.id!=='housing')box.append(node('p','내 기준 충족도 '+percentage(row.fit*100),'quiet'));
  if(row.criterion.hard)box.append(node('p',hardLabel(row.criterion)+' · '+({pass:'충족',fail:'미충족',unknown:'미확인'}[row.hardStatus]||'미확인'),'hard-note'));
  if(row.criterion.need)box.append(node('p',row.criterion.need,'quiet'));
  const detail=node('details');detail.append(node('summary','시설·원문·출처'),renderEvidence(row));box.append(detail);content.append(box);
 }
 for(const comparison of view?.comparisons||[])if(c.rows.some(r=>r.criterion.id===comparison.criterionId))content.append(node('p',comparison.text,'quiet'));
 if(c.id==='safety'&&view)appendSafety?.(content,view.place.id);
 extras?.(content,active);
}
