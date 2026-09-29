const $ = (q) => document.querySelector(q);
const names = {shops:"상가", bus:"정류장", cctv:"CCTV"};
const state = {data:null,map:null,region:null,overlays:[],visible:[],selected:null,tilesLoaded:false};
window.previewState = state;
function node(tag, text, className) {
  const e=document.createElement(tag); if(text!==undefined)e.textContent=text;
  if(className)e.className=className; return e;
}
function status(text, error=false) {$("#status").textContent=text;$("#status").dataset.state=error?"error":"ready";}
function updateStatus(){
  const prefix=state.tilesLoaded?"지도 타일 연결 완료":"지도 타일 연결 중";
  status(prefix+" · "+state.region.name+" · "+state.visible.length+"개 표본");
}
function selectedDetail(record){
  const root=$("#detail");root.replaceChildren();
  const title=node("h2",record.name);root.append(title,node("p",record.address||"주소 컬럼 미제공 · 진주시 버스정류장"));
  root.append(node("p",record.detail,"meta"));
  root.append(node("p",record.date_label+" "+record.date+" · 원본 "+record.source_row+"행 · "+record.source_id,"meta"));
  root.append(node("p","좌표 "+record.lat.toFixed(6)+", "+record.lon.toFixed(6),"meta"));
  const source=node("a","공식 원본 보기");source.href=record.source_url;source.target="_blank";source.rel="noopener noreferrer";root.append(source);
}
function choose(id, move=true){
  state.selected=id;
  const record=state.visible.find(r=>r.id===id);if(!record)return;
  selectedDetail(record);
  for(const e of document.querySelectorAll(".record"))e.setAttribute("aria-pressed",String(e.dataset.id===id));
  for(const o of state.overlays)o.button.classList.toggle("selected",o.id===id);
  if(move){state.map.panTo(new kakao.maps.LatLng(record.lat,record.lon));state.map.setLevel(3);}
}
function fit(){
  if(!state.visible.length){state.map.setCenter(new kakao.maps.LatLng(state.region.anchor.lat,state.region.anchor.lon));return;}
  const bounds=new kakao.maps.LatLngBounds();
  state.visible.forEach(r=>bounds.extend(new kakao.maps.LatLng(r.lat,r.lon)));
  state.map.setBounds(bounds,55,55,55,55);
}
function render(){
  const active=new Set([...document.querySelectorAll('input[name="kind"]:checked')].map(e=>e.value));
  state.visible=state.region.samples.filter(r=>active.has(r.kind));
  state.overlays.forEach(o=>o.overlay.setMap(null));state.overlays=[];
  const list=$("#items");list.replaceChildren();
  $("#count").textContent=state.visible.length+"개";
  const counters={shops:0,bus:0,cctv:0};
  for(const record of state.visible){
    const number=++counters[record.kind],short={shops:"상",bus:"정",cctv:"C"}[record.kind]+number;
    const button=node("button",short,"pin "+record.kind);button.type="button";button.setAttribute("aria-label",names[record.kind]+" "+record.name+" 지도 표본");
    button.addEventListener("click",()=>choose(record.id,false));
    const overlay=new kakao.maps.CustomOverlay({map:state.map,position:new kakao.maps.LatLng(record.lat,record.lon),content:button,yAnchor:1.1,zIndex:record.kind==="shops"?5:3});
    state.overlays.push({id:record.id,overlay,button});
    const row=node("button",undefined,"record");row.type="button";row.dataset.id=record.id;row.setAttribute("aria-pressed","false");
    const label=node("span",undefined,"label");label.append(node("span",undefined,"dot "+record.kind),document.createTextNode(names[record.kind]+" "+number));
    row.append(label,node("strong",record.name),node("small",record.address||record.detail),node("small",record.date_label+" "+record.date));
    row.addEventListener("click",()=>choose(record.id));list.append(row);
  }
  if(!state.visible.length){
    list.append(node("p","표시할 자료를 선택해.","empty"));
    $("#detail").replaceChildren(node("p","선택된 자료가 없어."));
    state.selected=null;
  }else choose(state.visible.some(r=>r.id===state.selected)?state.selected:state.visible[0].id,false);
  updateStatus();fit();
}
function quality(data){
  for(const s of data.quality){
    const tr=node("tr"),date=Object.keys(s.dates).join(", ");
    [names[s.id],s.jinju_rows.toLocaleString(),s.coordinate_screen_pass_rows.toLocaleString(),s.quarantined_rows.toLocaleString(),date+(s.id==="cctv"?" (공개본 수정일)":"")].forEach(v=>tr.append(node("td",v)));
    $("#quality").append(tr);
  }
  for(const source of data.sources){
    const a=node("a",names[source.id]+" 원본 · "+source.license);a.href=source.source_url;a.target="_blank";a.rel="noopener noreferrer";$("#sources").append(a);
  }
}
async function json(url){
  const response=await fetch(url,{cache:"no-store"});if(!response.ok)throw Error(url+" HTTP "+response.status);return response.json();
}
async function boot(){
  try{
    const [data,config]=await Promise.all([json("/api/samples"),json("/api/config")]);
    if(!data.regions?.length)throw Error("표본 자료가 비어 있어.");
    state.data=data;state.region=data.regions[0];quality(data);
    for(const r of data.regions){const option=node("option",r.name);option.value=r.id;$("#area").append(option);}
    if(!config.javascriptKey)throw Error("카카오 JavaScript 키 설정이 필요해.");
    const sdk=document.createElement("script");sdk.src="https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey="+encodeURIComponent(config.javascriptKey);
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error("지도 SDK 연결 시간 초과")),15000);sdk.onload=()=>{clearTimeout(timer);resolve();};sdk.onerror=()=>{clearTimeout(timer);reject(Error("지도 SDK 로드 실패"));};document.head.append(sdk);});
    if(!window.kakao?.maps)throw Error("지도 SDK 초기화 실패");
    await new Promise(resolve=>kakao.maps.load(resolve));
    state.map=new kakao.maps.Map($("#map"),{center:new kakao.maps.LatLng(state.region.anchor.lat,state.region.anchor.lon),level:4});
    state.map.addControl(new kakao.maps.ZoomControl(),kakao.maps.ControlPosition.RIGHT);
    kakao.maps.event.addListener(state.map,"tilesloaded",()=>{state.tilesLoaded=true;updateStatus();});
    $("#area").disabled=false;$("#reset").disabled=false;
    $("#area").addEventListener("change",()=>{state.region=data.regions.find(r=>r.id===$("#area").value);state.selected=null;render();});
    document.querySelectorAll('input[name="kind"]').forEach(e=>e.addEventListener("change",render));
    $("#reset").addEventListener("click",fit);
    let resizeFrame;
    window.addEventListener("resize",()=>{
      cancelAnimationFrame(resizeFrame);
      resizeFrame=requestAnimationFrame(()=>{state.map.relayout();fit();});
    });
    render();
  }catch(error){status("화면을 준비하지 못했어. "+error.message,true);}
}
boot();
