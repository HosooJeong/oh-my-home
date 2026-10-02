import {loadKakaoMaps} from './kakao-map.mjs';
const $=id=>document.getElementById(id);
let map,maps,token,start,end,mode='walk',target='start',busy=false,version=0;
let drawings=[];
const status=text=>{$('route-status').textContent=text;};
function clearResult(){version++;drawings.forEach(item=>item.setMap(null));drawings=[];$('route-results').replaceChildren();$('route-note').hidden=true;drawPoints();}
function drawPoints(){if(!map)return;for(const [point,label,style] of [[start,'출발',''],[end,'도착','end']])if(point){const element=document.createElement('span');element.className='route-pin '+style;element.textContent=label;const overlay=new maps.CustomOverlay({position:new maps.LatLng(point.latitude,point.longitude),content:element,map,yAnchor:1.2});drawings.push(overlay);}}
function controls(){
 $('start-label').textContent=start?.label||'지도에서 선택하세요';$('end-label').textContent=end?.label||'지도에서 선택하세요';
 for(const id of ['start','end'])$(id).setAttribute('aria-pressed',String(target===id));
 document.querySelectorAll('[data-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mode===mode)));
 $('walk-options').hidden=mode!=='walk';$('query').disabled=busy||!token||!start||!end||!map;
 for(const id of ['start','end','example','walk-option'])$(id).disabled=busy||!map;
 document.querySelectorAll('[data-mode]').forEach(button=>button.disabled=busy);
 $('query').textContent=busy?'경로 조회 중':'경로 조회';
}
function setPoint(id,point){if(busy)return;if(id==='start')start=point;else end=point;target=id==='start'?'end':'start';clearResult();controls();status('');}
function fit(){if(!map||!start||!end)return;const bounds=new maps.LatLngBounds();for(const p of [start,end])bounds.extend(new maps.LatLng(p.latitude,p.longitude));map.setBounds(bounds,40,40,40,40);}
function paint(route){
 drawings.forEach(item=>item.setMap(null));drawings=[];drawPoints();const bounds=new maps.LatLngBounds();
 for(const segment of route.segments){const path=segment.points.map(([lon,lat])=>{const position=new maps.LatLng(lat,lon);bounds.extend(position);return position;});const line=new maps.Polyline({map,path,strokeWeight:5,strokeColor:segment.mode==='WALKING'?'#326854':'#497fac',strokeOpacity:.85,strokeStyle:segment.mode==='WALKING'?'shortdash':'solid'});drawings.push(line);}
 for(const p of [start,end])bounds.extend(new maps.LatLng(p.latitude,p.longitude));map.setBounds(bounds,40,40,40,40);
}
function results(result){
 $('route-results').replaceChildren();result.routes.forEach((route,i)=>{const button=document.createElement('button');button.type='button';button.setAttribute('aria-pressed',String(i===0));const time=document.createElement('strong'),detail=document.createElement('small');time.textContent=`약 ${Math.max(1,Math.round(route.duration_s/60))}분`;detail.textContent=`${(route.distance_m/1000).toFixed(2)}km${route.transfers===null?'':` · 환승 ${route.transfers}회`}`;button.append(time,detail);button.addEventListener('click',()=>{$('route-results').querySelectorAll('button').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));paint(route);});$('route-results').append(button);});
 $('route-note').textContent=result.notice;$('route-note').hidden=false;paint(result.routes[0]);
}
async function initMap(){try{maps=await loadKakaoMaps();map=new maps.Map($('route-map'),{center:new maps.LatLng(35.18,128.11),level:6});maps.event.addListener(map,'click',event=>{if(busy)return;const p=event.latLng;setPoint(target,{latitude:p.getLat(),longitude:p.getLng(),label:`${p.getLat().toFixed(5)}, ${p.getLng().toFixed(5)}`});});new ResizeObserver(()=>{if(map){const center=map.getCenter();map.relayout();map.setCenter(center);}}).observe($('route-map'));$('map-retry').hidden=true;controls();}catch{status('지도를 불러오지 못했어요. 다시 시도해 주세요.');$('map-retry').hidden=false;}}
for(const id of ['start','end'])$(id).addEventListener('click',()=>{target=id;controls();});
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{mode=button.dataset.mode;clearResult();controls();status('');}));
$('walk-option').addEventListener('change',()=>{clearResult();status('');});
$('map-retry').addEventListener('click',initMap);
$('example').addEventListener('click',async()=>{
 if(!map||busy)return;busy=true;clearResult();controls();status('예시 위치를 찾고 있어요.');
 const geocoder=new maps.services.Geocoder();
 const address=(query,label)=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('timeout')),10000);geocoder.addressSearch(query,(rows,state)=>{clearTimeout(timer);if(state===maps.services.Status.OK&&rows.length===1)resolve({latitude:Number(rows[0].y),longitude:Number(rows[0].x),label});else reject(new Error('example'));});});
 try{[start,end]=await Promise.all([address('경남 진주시 동진로 155','진주시청'),address('경남 진주시 진주역로 130','진주역')]);clearResult();fit();status('');}catch{status('예시 위치를 찾지 못했어요. 지도에서 선택해 주세요.');}finally{busy=false;controls();}
});
$('query').addEventListener('click',async()=>{
 if(busy||!start||!end||!token)return;clearResult();const revision=version;busy=true;controls();status('경로 조회 중');const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
 try{const point=p=>({latitude:p.latitude,longitude:p.longitude});const response=await fetch('/api/routes',{method:'POST',headers:{'Content-Type':'application/json','X-Session':token},body:JSON.stringify({start:point(start),end:point(end),mode,walk_option:$('walk-option').value}),signal:controller.signal,cache:'no-store'});const result=await response.json();if(revision!==version)return;if(!response.ok){status(result.message||'경로 조회 요청을 확인해 주세요.');return;}results(result);status('');}
 catch(error){if(revision===version)status(error.name==='AbortError'?'경로 조회가 지연됐어요. 다시 시도해 주세요.':'경로 조회에 연결하지 못했어요. 다시 시도해 주세요.');}
 finally{clearTimeout(timer);busy=false;controls();}
});
async function init(){controls();try{const response=await fetch('/api/bootstrap',{cache:'no-store'});if(!response.ok)throw new Error();token=(await response.json()).token;const configured=await fetch('/api/routes/status',{cache:'no-store'});if(configured.ok&&!(await configured.json()).configured)status('경로 API의 서버 키를 설정해야 해요.');}catch{status('서버에 연결하지 못했어요. 새로고침해 주세요.');}await initMap();}
init();
