import {CATEGORIES} from './village-model.mjs';
import {utilityLabel,hardLabel,profileWeights,measure,proposedComparison} from './analysis-view.mjs';
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const valid=r=>r.known&&finite(r.fit)&&r.fit>=0&&r.fit<=1;
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
export const percentage=n=>finite(n)?n.toFixed(1).replace(/\.0$/,'')+'%':'미확인';
const distancePreferences={
 convenience_straight_line_distance_m:['편의점','편의점이 가까운 생활을 원하는 선호'],
 grocery_straight_line_distance_m:['마트','장보는 곳이 가까운 생활을 원하는 선호'],
 house_to_grocery_straight_line_distance_m:['마트','장보는 곳이 가까운 생활을 원하는 선호'],
 bus_stop_straight_line_distance_m:['정류장','정류장이 가까운 생활을 원하는 선호'],
 school_straight_line_distance_m:['학교','학교가 가까운 생활을 원하는 선호'],
 park_straight_line_distance_m:['공원','가까운 공원을 원하는 선호'],
 library_straight_line_distance_m:['도서관','가까운 도서관을 원하는 선호'],
 meeting_straight_line_distance_m:['약속 장소','약속 장소가 가까웠으면 하는 선호']
};
const metres=n=>Math.round(n).toLocaleString('ko-KR')+'m';
function preferenceFit(row,preference){
 if(row.fit===1)return preference+'에 잘 맞는 위치예요.';
 if(row.fit===0)return '거리 기준에서는 '+preference+'와 차이가 큰 편이에요.';
 return preference+'에는 조금 아쉬운 위치예요.';
}
export function criterionReason(row){
 if(!valid(row))return ({'자료 충돌':'자료가 서로 맞지 않아 선호 충족 여부를 아직 판단하기 어려워요.','조회 실패':'자료 조회를 완료하지 못해 선호 충족 여부는 미확인이에요.','현재 정량 평가 미지원':'현재 연결된 자료로는 이 요청의 충족 여부를 평가하기 어려워요.'}[row.reason]||row.reason+' 때문에 선호 충족 여부는 미확인이에요.');
 const c=row.criterion,value=row.fact?.value,u=c.utility,distance=distancePreferences[c.metric];
 if(distance&&u?.unit==='m'&&u.direction==='lower'&&row.fact?.unit==='m'&&finite(value)&&value>=0){
  // Only name the facility that supplied this candidate's bound measurement.
  const facility=row.facilities?.find(f=>f.id===row.fact.source_record&&typeof f.name==='string'&&f.name.trim());
  const place=c.metric==='meeting_straight_line_distance_m'?'지정하신 '+(facility?.name||c.parameters?.meeting_label||'약속 장소'):facility?'등록자료에서 가장 가까운 '+facility.name:'등록자료로 확인한 '+distance[0];
  const flexible=proposedComparison(c)&&c.comparison_proposal.label==='조금 멀어도 괜찮아요';
  const preference=flexible?distance[0]+'는 조금 멀어도 괜찮다는 선호':distance[1];
  return place+'까지 집에서 직선거리 '+metres(value)+'예요. '+preferenceFit(row,preference);
 }
 if(c.metric==='academy_count_within_radius'&&u?.unit==='count'&&row.fact?.unit==='count'&&finite(value)&&value>=0){
  const p=c.parameters||{},radius=Number(p.radius_m),level={elementary:'초등학생',middle:'중학생',high:'고등학생'}[p.school_level],subject={math:'수학',english:'영어',korean:'국어',science:'과학',art:'미술',music:'음악'}[p.subject];
  const scope=finite(radius)&&radius>0?'집을 중심으로 직선반경 '+metres(radius)+' 안에서 ':'조회 범위에서 ',target=[level,subject,'학원'].filter(Boolean).join(' ');
  const names=[...new Set((row.facilities||[]).filter(f=>f.kind==='academy'&&typeof f.name==='string'&&f.name.trim()).map(f=>f.name))].slice(0,2);
  const examples=value>0&&names.length?' '+names.join(', ')+' 같은 학원이 비교 대상이에요.':'';
  const fit=row.fit===1?'학원 선택지가 다양했으면 하는 선호에 잘 맞는 편이에요.':row.fit===0?(value===0?'등록자료에서 원하는 학원이 확인되지 않아 선택지가 다양했으면 하는 선호에는 아쉬워요.':'확인된 선택지는 있지만 학원이 다양했으면 하는 선호와는 차이가 큰 편이에요.'):'학원 선택지가 다양했으면 하는 선호에는 일부만 맞아요.';
  return scope+target+' '+value.toLocaleString('ko-KR')+'곳을 등록자료로 확인했어요.'+examples+' '+fit;
 }
 if(row.fit===1)return '설정한 목표 수준을 충족해요.';
 if(u?.direction==='boolean')return '원하는 조건과 일치하지 않아요.';
 if(!u||!finite(value))return '목표 수준에 미치지 못해요.';
 const difference=measure(Math.abs(value-u.ideal),u.unit).replace(' · 직선거리','').replace(' · 등록자료','');
 if(u.direction==='target')return '원하는 수준과 '+difference+' 차이가 있어요.';
 return '목표보다 '+difference+(u.direction==='higher'?' 적어요.':u.unit==='m'?' 더 멀어요.':' 높아요.');
}

export function overviewReasons(view){
 return (view?.rows||[]).filter(r=>valid(r)&&r.weight>0&&(distancePreferences[r.criterion.metric]||r.criterion.metric==='academy_count_within_radius')).sort((a,b)=>b.weight-a.weight).slice(0,2).map(criterionReason);
}
export function categoryScope(category){
 const metrics=new Set(category.rows.filter(valid).map(r=>r.criterion.metric)),notes=[];
 if([...metrics].some(m=>distancePreferences[m]))notes.push('거리 평가는 위치 간 직선거리 기준이며 실제 이동 경로·시간은 미확인이에요.');
 if(category.id==='living'&&metrics.size)notes.push('매장의 현재 영업 여부는 별도 확인이 필요해요.');
 if(metrics.has('bus_stop_straight_line_distance_m'))notes.push('이용할 노선·방향·배차는 아직 확인하지 않았어요.');
 if(metrics.has('school_straight_line_distance_m'))notes.push('가까운 학교가 배정 학교를 뜻하지는 않으며 통학로 안전은 별도 확인이 필요해요.');
 if(metrics.has('academy_count_within_radius'))notes.push('등록된 선택지 비교이며 수업의 질·현재 모집 여부를 평가한 결과는 아니에요.');
 if(metrics.has('park_straight_line_distance_m')||metrics.has('library_straight_line_distance_m'))notes.push('현재 이용 가능성과 시설별 이용 규칙은 별도 확인이 필요해요.');
 return notes.join(' ');
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
 for(const item of data.safety?.items||[])for(const x of item.excerpts||[])if((category==='overview'||category==='safety')&&include(x))notes.push({kind:'area',title:item.area_name,excerpt:x,scope:'지역 공식 자료 · 집별 안전 판정 미확인'});
 for(const item of data.leisure?.discoveries||[]){
  const matching=category==='overview'||category==='leisure'&&requests.some(r=>r.module==='leisure'&&r.criterion_ids?.includes(item.criterion_id));
  for(const x of item.excerpts||[])if((category==='overview'||category==='leisure')&&include(x))notes.push({kind:'discovery',title:item.name,excerpt:x,role:item.role_label,scope:'시설 발견 참고 · 거리·이용 가능성 미확인'});
  if(matching&&!item.excerpts?.length)notes.push({kind:'discovery',title:item.name,note:item.note,url:item.source_url,scope:'시설 후보 · 조건 충족 근거 미확인'});
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
 root.replaceChildren(svg,...(geo.axes.some(a=>a.target!==null)?[legend]:[]),node('figcaption',geo.axes.some(a=>a.target!==null)?'목표 100 · 미확인은 빈 구간':'실거래 참고 · 집별 충족도 미평가','quiet'));
}

function scoreText(c){return c.score!==null?'목표 대비 '+percentage(c.score):c.status==='reference'?'실거래 참고':c.status==='unselected'?'미선택':c.range&&c.coverage>0?'일부 미확인 · 가능한 충족도 '+percentage(c.range[0])+'–'+percentage(c.range[1]):'목표 충족 여부 미확인';}
export function renderReport({tabs,content,categories,view,profile,active='overview',onSelect,renderEvidence,appendSafety,selectionReason,extras}){
 const choices=[{id:'overview',short:'총평',color:'#276b51'},...categories];tabs.replaceChildren();
 choices.forEach((c,i)=>{const b=node('button',c.short,'report-tab');b.type='button';b.id='report-tab-'+c.id;b.dataset.category=c.id;b.style.setProperty('--brick-color',c.color);b.setAttribute('role','tab');b.setAttribute('aria-selected',String(c.id===active));b.setAttribute('aria-controls','report-content');b.tabIndex=c.id===active?0:-1;b.addEventListener('click',()=>onSelect(c.id,true));b.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(i+1)%choices.length;else if(event.key==='ArrowLeft')next=(i+choices.length-1)%choices.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=choices.length-1;else return;event.preventDefault();onSelect(choices[next].id,true);});tabs.append(b);});
 content.replaceChildren();content.setAttribute('aria-labelledby','report-tab-'+active);
 if(active==='overview'){
  content.append(node('h3','총평'));
  if(!view){content.append(node('p','집별 충족도 미평가 · 실거래 참고','report-lead'));extras?.(content,active);return;}
  const a=view.assessment;
  content.append(node('p',a.score===null?`확인한 비중 ${percentage(a.coverage*100)} · 전체 순위 보류`:`설정한 조건의 충족도는 ${percentage(a.score)}예요.`, 'report-lead'));
  for(const reason of overviewReasons(view))content.append(node('p',reason,'report-explanation'));
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
 if(!c.rows.length&&c.id!=='housing')content.append(node('p','수치 평가 조건 미설정','quiet'));
 for(const row of c.rows){
  const box=node('article',undefined,'report-condition');box.append(node('h4',row.criterion.label),node('p',criterionReason(row),'report-explanation'));
  if(valid(row))box.append(node('p',row.measure+(c.id!=='housing'?' · 내 기준 충족도 '+percentage(row.fit*100):''),'quiet'));
  if(row.criterion.hard)box.append(node('p',hardLabel(row.criterion)+' · '+({pass:'충족',fail:'미충족',unknown:'미확인'}[row.hardStatus]||'미확인'),'hard-note'));
  const detail=node('details');detail.append(node('summary','시설·원문·출처'),node('p',utilityLabel(row.criterion,true),'quiet'));if(row.criterion.need)detail.append(node('p',row.criterion.need,'original-need'));detail.append(renderEvidence(row));box.append(detail);content.append(box);
 }
 const scope=categoryScope(c);if(scope)content.append(node('p',scope,'quiet'));
 for(const comparison of view?.comparisons||[])if(c.rows.some(r=>r.criterion.id===comparison.criterionId))content.append(node('p',comparison.text,'quiet'));
 if(c.id==='safety'&&view)appendSafety?.(content,view.place.id);
 extras?.(content,active);
}
