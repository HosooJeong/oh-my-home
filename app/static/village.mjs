import {loadKakaoMaps} from './kakao-map.mjs';
import {CATEGORIES,STORAGE_KEY,RADII,readDraft,buildRequest,evaluationShares as shares,levelForPosition,toggleCategory,moveBlock} from './village-model.mjs';
import {createVillageWorld} from './village-world.mjs';
import {entryReady,addCandidate} from './entry-places.mjs';
import {debugEvent} from './debug-session.mjs';

const $=id=>document.getElementById(id);
let draft;
try{draft=readDraft(sessionStorage.getItem(STORAGE_KEY));}catch{draft=readDraft(null);}
let mode=draft.entry?(entryReady(draft)?'town':'location'):'start',order=[],step=0,world=null;
let entryMap=null,entryMapLoading=null,geocoder=null,markers=[],pendingPlace=null,locationVersion=0;
let motion=!matchMedia('(prefers-reduced-motion: reduce)').matches;
const buttons=new Map();
// Original SVG line icons share one stroke and never depend on font glyphs.
const ICONS={
 home:['M3 10 12 3l9 7','M5 9v12h14V9','M9 21v-7h6v7'],
 houses:['M2 12 8 7l6 5','M4 11v10h8V11','M12 7l5-4 5 4','M14 6v9h6V6'],
 search:['M16 16l5 5','M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
 'arrow-left':['M20 12H4','m10 6-6 6 6 6'],
 'arrow-right':['M4 12h16','m14 6 6 6-6 6'],
 'rotate-left':['M3 8h5V3','M3 8a9 9 0 1 1-1 8'],
 'rotate-right':['M21 8h-5V3','M21 8a9 9 0 1 0 1 8'],
 'zoom-in':['M17 17l4 4','M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0','M6 10h8','M10 6v8'],
 'zoom-out':['M17 17l4 4','M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0','M6 10h8'],
 remove:['m6 6 12 12','M18 6 6 18'],
 living:['M3 6h3l2 12h11l2-9H7','M9 21h.1','M18 21h.1'],
 health:['M9 3h6v6h6v6h-6v6H9v-6H3V9h6Z'],
 dining:['M4 3v7a3 3 0 0 0 6 0V3','M7 3v19','M19 3c-3 3-3 7-3 10h3','M19 3v19'],
 transport:['M5 17V6a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v11Z','M5 10h14','M8 3v7','M8 14h.1','M16 14h.1','M7 17v4','M17 17v4'],
 education:['M12 5v16','M12 5C9 3 5 3 2 5v14c3-2 7-2 10 2 3-4 7-4 10-2V5c-3-2-7-2-10 0'],
 safety:['M12 2 3 6v6c0 5 5 8 9 10 4-2 9-5 9-10V6Z','m8 12 3 3 5-6'],
 leisure:['M8 3 3 10h3l-4 6h12l-4-6h3Z','M8 16v6','M18 6l3 5h-2l3 5h-7','M18 16v6'],
 housing:['M14 9a5 5 0 1 1-10 0 5 5 0 0 1 10 0','m13 12 9 9','m17 16 3-3','m19 18 3-3']
};
function icon(name){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('icon');
 for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.75','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
 for(const d of ICONS[name]){const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path);}return svg;
}
document.querySelectorAll('[data-icon]').forEach(el=>el.append(icon(el.dataset.icon)));
const status=message=>$('village-status').textContent=message;
function save(){try{sessionStorage.setItem(STORAGE_KEY,JSON.stringify(draft));}catch{status('입력을 저장하지 못했어요.');}}
function renderExamples(category){
 const group=$('question-examples');group.replaceChildren();group.hidden=!category.examples?.length;
 group.setAttribute('aria-label',category.label+' 입력 예시');group.style.setProperty('--sample-color',category.color);$('question-sample-status').textContent='';
 for(const example of category.examples||[]){
  const button=document.createElement('button');button.type='button';button.textContent=example.label;
  button.addEventListener('click',()=>{
   if(mode!=='detail'||order[step]!==category.id)return;
   const answer=$('category-answer'),current=answer.value;
   const next=current.split('\n').includes(example.text)?current:current?current+'\n\n'+example.text:example.text;
   if(next.length>answer.maxLength){$('question-sample-status').textContent='예시를 추가하면 450자를 넘어요. 입력 내용을 줄여 주세요.';return;}
   answer.value=next;answer.dispatchEvent(new Event('input',{bubbles:true}));answer.focus();answer.setSelectionRange(next.length,next.length);
  });group.append(button);
 }
}
function snapshot(){
 const percentages=shares(draft.blocks);
 return {mode,coordinate_system:'virtual floor: origin=home; X/Z horizontal; Y height; camera never changes priorities',focus:draft.focus,
  blocks:draft.blocks.map(b=>({...b,level:levelForPosition(b.x,b.z),share:percentages[b.id]})),candidate_count:draft.entry==='discover'?0:draft.candidates.length,entry_ready:entryReady(draft),camera_yaw:world?.yaw??null,camera_pose:world?.pose??null,dragging:world?.dragId??null,webgl:!!world?.available,motion};
}
function expose(){const value=JSON.stringify(snapshot());$('scene-state').value=value;$('scene-state').textContent=value;}
window.render_game_to_text=()=>JSON.stringify(snapshot());
window.advanceTime=ms=>{if(world)world.advance(Math.max(0,Math.min(Number(ms)||0,10000))/1000);};

for(const c of CATEGORIES){
 const button=document.createElement('button');button.type='button';button.dataset.category=c.id;button.style.setProperty('--brick-color',c.color);
 const mark=document.createElement('span');mark.className='category-icon';mark.append(icon(c.id));
 button.append(mark,document.createTextNode(c.label));buttons.set(c.id,button);$('category-tray').append(button);
 button.addEventListener('click',()=>{if(toggleCategory(draft,c.id)){draft.handoff=false;save();render();status('');}});
}
function render(){
 $('village-app').dataset.mode=mode;
 $('scene-wrap').hidden=mode==='location';
 $('entry-panel').hidden=mode!=='start';$('location-panel').hidden=mode!=='location';
 $('town-tools').hidden=mode!=='town';$('detail-panel').hidden=!['detail','review'].includes(mode);
 $('question-view').hidden=mode!=='detail';$('review-view').hidden=mode!=='review';
 $('change-start').hidden=mode!=='town';$('scene-controls').hidden=mode!=='town';$('scene-wrap').querySelector('.scene-heading').hidden=['detail','review'].includes(mode);
 $('location-title').textContent=draft.entry==='discover'?'관심 지역':draft.entry==='single'?'집 선택':'비교할 집';
 $('discover-location').hidden=draft.entry!=='discover';$('known-location').hidden=draft.entry==='discover';
 $('enter-town').disabled=!entryReady(draft);$('enter-town').firstChild.textContent='다음';
 $('location-input').value=draft.location;
 renderEntryPlaces();
 const percentages=shares(draft.blocks);
 for(const c of CATEGORIES){const button=buttons.get(c.id),active=draft.blocks.some(b=>b.id===c.id);button.setAttribute('aria-pressed',String(active));button.disabled=active&&draft.blocks.length===1;button.setAttribute('aria-label',c.label+(active?(c.id==='housing'?', 실거래 참고':`, 반영 비중 ${percentages[c.id]}%`):''));}
 $('open-details').disabled=!draft.blocks.length||!world?.available;
 if(mode==='detail'){
  const c=CATEGORIES.find(c=>c.id===order[step]);draft.focus=c.id;
  $('question-progress').textContent=`${step+1}/${order.length}`;$('question-category').textContent=c.label;$('question-label').textContent=c.question;
  $('question-mark').style.setProperty('--brick-color',c.color);$('question-mark').replaceChildren(icon(c.id));$('category-answer').value=draft.answers[c.id]||'';$('category-answer').placeholder=c.placeholder;
  renderExamples(c);
  $('question-prev').hidden=step===0;$('question-next-label').textContent=step===order.length-1?'입력 확인':'다음';
 }else if(mode==='review'){
  $('question-progress').textContent=`${order.length}/${order.length}`;$('answer-summary').replaceChildren();
  $('extra-request').value=draft.extra||'';$('review-note').textContent=draft.legacy?.length?'기존 안전·비용 조건은 추가 조건으로 보존했어요.':'';
  for(const id of order){const c=CATEGORIES.find(c=>c.id===id),row=document.createElement('div');row.className='answer-item';const name=document.createElement('strong'),percent=document.createElement('span'),answer=document.createElement('p');name.textContent=c.label;percent.textContent=id==='housing'?'참고':percentages[id]+'%';name.append(percent);answer.textContent=draft.answers[id]?.trim()||'나중에 정할게요';row.append(name,answer);$('answer-summary').append(row);}
  for(const r of draft.legacy||[]){const row=document.createElement('div');row.className='answer-item';const name=document.createElement('strong'),answer=document.createElement('p');name.textContent=r.id==='housing'?'기존 집·비용 조건':'기존 안전·환경 조건';answer.textContent=r.answer;row.append(name,answer);$('answer-summary').append(row);}
 }
 world?.present({mode,focus:mode==='detail'?draft.focus:null});world?.sync();expose();
}
document.querySelectorAll('[data-entry]').forEach(b=>b.addEventListener('click',()=>{draft.entry=b.dataset.entry;draft.handoff=false;locationVersion++;pendingPlace=null;$('map-pick').hidden=true;$('address-results').replaceChildren();$('address-status').textContent='';$('location-error').hidden=true;mode='location';save();render();debugEvent('entry_selected',{entry:draft.entry});if(draft.entry!=='discover')loadEntryMap();}));
$('location-input').addEventListener('input',event=>{draft.location=event.target.value.slice(0,200);save();});
$('location-back').addEventListener('click',()=>{locationVersion++;mode='start';render();});
$('change-start').addEventListener('click',()=>{mode='start';world?.cancelDrag();render();});
$('enter-town').addEventListener('click',()=>{if(mode!=='location'||!entryReady(draft))return;locationVersion++;mode='town';save();render();debugEvent('candidates_confirmed',{entry:draft.entry,location:draft.entry==='discover'?draft.location:null,candidates:draft.entry==='discover'?[]:draft.candidates});status(draft.blocks.length?'':'블록을 집 주변에 놓아주세요.');});
$('open-details').addEventListener('click',()=>{if(mode!=='town'||!draft.blocks.length||!world?.available)return;world.cancelDrag();order=draft.blocks.slice().sort((a,b)=>levelForPosition(a.x,a.z)-levelForPosition(b.x,b.z)).map(b=>b.id);step=0;mode='detail';save();status('');render();window.scrollTo(0,0);});
$('back-town').addEventListener('click',()=>{mode='town';render();window.scrollTo(0,0);});
$('category-answer').addEventListener('input',event=>{draft.answers[order[step]]=event.target.value.slice(0,450);draft.handoff=false;$('question-sample-status').textContent='';save();});
function nextQuestion(){const c=CATEGORIES.find(c=>c.id===order[step]);debugEvent('category_answer',{category:c.id,question:c.question,answer:draft.answers[c.id]||''});if(step<order.length-1)step++;else mode='review';save();render();window.scrollTo(0,0);}
$('question-next').addEventListener('click',nextQuestion);
$('question-prev').addEventListener('click',()=>{step=Math.max(0,step-1);render();});
$('question-unknown').addEventListener('click',()=>{draft.answers[order[step]]='';nextQuestion();});
$('extra-request').addEventListener('input',event=>{draft.extra=event.target.value;draft.handoff=false;save();});
$('continue-workspace').addEventListener('click',async()=>{if(mode!=='review'||!entryReady(draft))return;const request=buildRequest(draft);if(request.length>4000){$('review-note').textContent='조건이 길어졌어요. 입력 내용을 조금 줄여 주세요.';return;}draft.handoff=true;save();$('continue-workspace').disabled=true;await debugEvent('village_confirmed',{entry:draft.entry,location:draft.location,candidates:draft.entry==='discover'?[]:draft.candidates,blocks:draft.blocks,answers:draft.answers,request});location.assign('/analysis');});
$('turn-left').addEventListener('click',()=>world?.rotate(-Math.PI/4));$('turn-right').addEventListener('click',()=>world?.rotate(Math.PI/4));
$('zoom-in').addEventListener('click',()=>world?.zoom(1.15));$('zoom-out').addEventListener('click',()=>world?.zoom(1/1.15));
document.addEventListener('keydown',event=>{if(mode==='town'&&event.key.toLowerCase()==='f'&&!['INPUT','TEXTAREA'].includes(event.target.tagName)){if(document.fullscreenElement)document.exitFullscreen?.();else $('scene-wrap').requestFullscreen?.();}});
render();
if(mode==='location'&&draft.entry!=='discover')loadEntryMap();

function locationError(message){$('location-error').textContent=message;$('location-error').hidden=!message;}
function renderEntryPlaces(){
 $('entry-place-list').replaceChildren();for(const [i,p] of draft.candidates.entries()){
  const row=document.createElement('li'),name=document.createElement('span'),remove=document.createElement('button');name.textContent=`${i+1}. ${p.label}`;remove.type='button';remove.setAttribute('aria-label',p.label+' 삭제');remove.append(icon('remove'));remove.addEventListener('click',()=>{draft.candidates=draft.candidates.filter(x=>x.id!==p.id);draft.handoff=false;save();debugEvent('candidates_confirmed',{operation:'removed',entry:draft.entry,candidates:draft.candidates,ready:entryReady(draft)});render();drawEntryMap();});row.append(name,remove);$('entry-place-list').append(row);
 }$('entry-place-count').textContent=draft.entry==='single'?'':`${draft.candidates.length}/6`;
}
function selectEntryPlace(place){try{addCandidate(draft,{id:'home_'+crypto.randomUUID().replaceAll('-',''),...place,origin:'user'});locationError('');pendingPlace=null;$('map-pick').hidden=true;$('address-results').replaceChildren();$('address-status').textContent='';save();debugEvent('candidates_confirmed',{operation:'selected',entry:draft.entry,candidates:draft.candidates,ready:entryReady(draft)});render();drawEntryMap(true);}catch(e){locationError(e.message);}}
function drawEntryMap(fit=false){
 if(!entryMap)return;markers.forEach(m=>m.setMap(null));markers=[];const bounds=new kakao.maps.LatLngBounds();
 for(const p of [...draft.candidates,...(pendingPlace?[pendingPlace]:[])]){const position=new kakao.maps.LatLng(p.latitude,p.longitude);bounds.extend(position);markers.push(new kakao.maps.Marker({map:entryMap,position}));}
 if(fit&&markers.length)requestAnimationFrame(()=>{entryMap.relayout();if(markers.length===1){entryMap.setCenter(bounds.getSouthWest());entryMap.setLevel(4);}else entryMap.setBounds(bounds,35,35,35,35);});
}
async function loadEntryMap(){
 if(entryMap){requestAnimationFrame(()=>{entryMap.relayout();drawEntryMap(true);});return;}
 if(entryMapLoading)return entryMapLoading;
 $('entry-map-state').hidden=false;$('entry-map-fallback').textContent='지도 로딩 중';$('entry-map-retry').hidden=true;
 entryMapLoading=(async()=>{let stage='sdk';try{
  const maps=await loadKakaoMaps();stage='map';
  entryMap=new maps.Map($('entry-map'),{center:new maps.LatLng(35.1796,128.1076),level:7});
  geocoder=new maps.services.Geocoder();$('entry-map-state').hidden=true;$('address-status').textContent='';
  maps.event.addListener(entryMap,'click',event=>{
   if(mode!=='location'||draft.entry==='discover')return;const version=++locationVersion;
   pendingPlace={label:'지도에서 선택한 집',latitude:event.latLng.getLat(),longitude:event.latLng.getLng()};$('map-pick-label').textContent=pendingPlace.label;$('map-pick').hidden=false;drawEntryMap();
   geocoder.coord2Address(pendingPlace.longitude,pendingPlace.latitude,(results,status)=>{if(version!==locationVersion||!pendingPlace)return;if(status===maps.services.Status.OK&&results[0]){pendingPlace.label=results[0].road_address?.address_name||results[0].address?.address_name||pendingPlace.label;$('map-pick-label').textContent=pendingPlace.label;}});
  });new ResizeObserver(()=>{if(!entryMap)return;const center=entryMap.getCenter();entryMap.relayout();if(draft.candidates.length>1)drawEntryMap(true);else entryMap.setCenter(center);}).observe($('entry-map'));drawEntryMap(true);
 }catch(error){entryMap=null;geocoder=null;const failedStage=error?.stage||stage;$('entry-map-fallback').dataset.failureStage=failedStage;debugEvent('analysis_error',{phase:'entry_map',stage:failedStage,error_name:error?.name||'load_failed'});$('entry-map-fallback').textContent='지도를 불러오지 못했어요.';$('entry-map-state').hidden=false;$('entry-map-retry').hidden=false;}
 finally{entryMapLoading=null;}})();return entryMapLoading;
}
$('entry-map-retry').addEventListener('click',loadEntryMap);
$('address-form').addEventListener('submit',async event=>{
 event.preventDefault();const query=$('address-input').value.trim();if(!query)return;await loadEntryMap();if(!geocoder)return;
 const version=++locationVersion;$('address-status').textContent='주소 검색 중';$('address-results').replaceChildren();$('address-search').disabled=true;
 const timer=setTimeout(()=>{if(version!==locationVersion)return;locationVersion++;$('address-search').disabled=false;$('address-status').textContent='검색이 지연되고 있어요. 다시 검색해 주세요.';},15000);
 geocoder.addressSearch(query,(results,status)=>{
  clearTimeout(timer);if(version!==locationVersion){$('address-search').disabled=false;return;}$('address-search').disabled=false;
  if(status!==kakao.maps.services.Status.OK||!results.length){$('address-status').textContent='검색 결과가 없어요. 주소를 확인해 주세요.';return;}
  $('address-status').textContent='';
  for(const result of results.slice(0,6)){const place={label:result.road_address?.address_name||result.address_name,latitude:Number(result.y),longitude:Number(result.x)},button=document.createElement('button');button.type='button';button.textContent=place.label;button.addEventListener('click',()=>selectEntryPlace(place));$('address-results').append(button);}
 },{size:6});
});
$('confirm-map-pick').addEventListener('click',()=>{if(pendingPlace){locationVersion++;selectEntryPlace(pendingPlace);}});

try{
 const THREE=await import('./vendor/three/three.module.min.js');
 world=createVillageWorld(THREE,{canvas:$('village-canvas'),container:$('scene-wrap'),labelsRoot:$('block-labels'),fallback:$('fallback-note'),getDraft:()=>draft,getMode:()=>mode,onChange:render,onSave:save,onStatus:status,onState:expose});render();
}catch(error){$('fallback-note').hidden=false;console.warn('Village 3D unavailable:',error.message);expose();}
