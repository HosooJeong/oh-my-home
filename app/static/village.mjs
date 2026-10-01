import {CATEGORIES,STORAGE_KEY,RADII,readDraft,evaluationShares as shares,levelForPosition,toggleCategory,moveBlock} from './village-model.mjs';
import {createToyModels,addToyStudio} from './village-models.mjs';

const $=id=>document.getElementById(id);
let draft;
try{draft=readDraft(sessionStorage.getItem(STORAGE_KEY));}catch{draft=readDraft(null);}
let mode=draft.entry?'town':'start',order=[],step=0,world=null;
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
 living:['M12 21 3.8 13a5.2 5.2 0 0 1 7.4-7.3L12 6.5l.8-.8a5.2 5.2 0 0 1 7.4 7.3Z','M8 11h8','M12 7v8'],
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
function save(){try{sessionStorage.setItem(STORAGE_KEY,JSON.stringify(draft));}catch{status('현재 화면에서는 입력 저장을 사용할 수 없어.');}}
function snapshot(){
 const percentages=shares(draft.blocks);
 return {mode,coordinate_system:'virtual floor: origin=home; X/Z horizontal; Y height; camera never changes priorities',focus:draft.focus,
  blocks:draft.blocks.map(b=>({...b,level:levelForPosition(b.x,b.z),share:percentages[b.id]})),camera_yaw:world?.yaw??null,dragging:world?.dragId??null,webgl:!!world?.available,motion};
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
 $('scene-wrap').hidden=['detail','review'].includes(mode);
 $('entry-panel').hidden=mode!=='start';$('location-panel').hidden=mode!=='location';
 $('town-tools').hidden=mode!=='town';$('detail-panel').hidden=!['detail','review'].includes(mode);
 $('question-view').hidden=mode!=='detail';$('review-view').hidden=mode!=='review';
 $('change-start').hidden=mode!=='town';$('scene-controls').hidden=mode!=='town';
 $('location-title').textContent=draft.entry==='discover'?'어느 생활권에서 찾을까?':draft.entry==='single'?'어느 집을 분석할까?':'어느 집들을 비교할까?';
 $('location-label').textContent=draft.entry==='discover'?'진주 안에서 찾을 지역':'집 이름·동네 메모';
 $('location-input').placeholder=draft.entry==='discover'?'예: 진주 전체, 평거동':'예: 평거동의 집 · 위치는 지도에서 선택';
 $('location-input').value=draft.location;
 const percentages=shares(draft.blocks);
 for(const c of CATEGORIES){const button=buttons.get(c.id),active=draft.blocks.some(b=>b.id===c.id);button.setAttribute('aria-pressed',String(active));button.disabled=active&&draft.blocks.length===1;button.setAttribute('aria-label',c.label+(active?(c.id==='housing'?', 실거래 참고':`, 반영 비중 ${percentages[c.id]}%`):''));}
 $('open-details').disabled=!draft.blocks.length||!world?.available;
 if(mode==='detail'){
  const c=CATEGORIES.find(c=>c.id===order[step]);draft.focus=c.id;
  $('question-progress').textContent=`${step+1}/${order.length}`;$('question-category').textContent=c.label;$('question-label').textContent=c.question;
  $('question-mark').style.setProperty('--brick-color',c.color);$('question-mark').replaceChildren(icon(c.id));$('category-answer').value=draft.answers[c.id]||'';$('category-answer').placeholder=c.placeholder;
  $('question-prev').hidden=step===0;$('question-next-label').textContent=step===order.length-1?'입력 확인':'다음';
 }else if(mode==='review'){
  $('question-progress').textContent=`${order.length}/${order.length}`;$('answer-summary').replaceChildren();
  for(const id of order){const c=CATEGORIES.find(c=>c.id===id),row=document.createElement('div');row.className='answer-item';const name=document.createElement('strong'),percent=document.createElement('span'),answer=document.createElement('p');name.textContent=c.label;percent.textContent=id==='housing'?'참고':percentages[id]+'%';name.append(percent);answer.textContent=draft.answers[id]?.trim()||'아직 모르겠어';row.append(name,answer);$('answer-summary').append(row);}
 }
 world?.sync();expose();
}
document.querySelectorAll('[data-entry]').forEach(b=>b.addEventListener('click',()=>{draft.entry=b.dataset.entry;mode='location';save();render();}));
$('location-input').addEventListener('input',event=>{draft.location=event.target.value.slice(0,200);save();});
$('location-back').addEventListener('click',()=>{mode='start';render();});
$('change-start').addEventListener('click',()=>{mode='start';world?.cancelDrag();render();});
$('enter-town').addEventListener('click',()=>{mode='town';save();render();status(draft.blocks.length?'':'블록을 골라 집 주변에 놓아봐.');});
$('open-details').addEventListener('click',()=>{if(mode!=='town'||!draft.blocks.length||!world?.available)return;world.cancelDrag();order=draft.blocks.slice().sort((a,b)=>levelForPosition(a.x,a.z)-levelForPosition(b.x,b.z)).map(b=>b.id);step=0;mode='detail';save();status('');render();window.scrollTo(0,0);});
$('back-town').addEventListener('click',()=>{mode='town';render();window.scrollTo(0,0);});
$('category-answer').addEventListener('input',event=>{draft.answers[order[step]]=event.target.value.slice(0,450);draft.handoff=false;save();});
function nextQuestion(){if(step<order.length-1)step++;else mode='review';save();render();window.scrollTo(0,0);}
$('question-next').addEventListener('click',nextQuestion);
$('question-prev').addEventListener('click',()=>{step=Math.max(0,step-1);render();});
$('question-unknown').addEventListener('click',()=>{draft.answers[order[step]]='';nextQuestion();});
$('continue-workspace').addEventListener('click',()=>{if(mode!=='review')return;draft.handoff=true;save();location.assign('/analysis');});
$('turn-left').addEventListener('click',()=>world?.rotate(-Math.PI/4));$('turn-right').addEventListener('click',()=>world?.rotate(Math.PI/4));
$('zoom-in').addEventListener('click',()=>world?.zoom(1.15));$('zoom-out').addEventListener('click',()=>world?.zoom(1/1.15));
document.addEventListener('keydown',event=>{if(mode==='town'&&event.key.toLowerCase()==='f'&&!['INPUT','TEXTAREA'].includes(event.target.tagName)){if(document.fullscreenElement)document.exitFullscreen?.();else $('scene-wrap').requestFullscreen?.();}});
render();

try{
 const THREE=await import('./vendor/three/three.module.min.js');
 world=createWorld(THREE);render();
}catch(error){$('fallback-note').hidden=false;console.warn('Village 3D unavailable:',error.message);expose();}

function createWorld(T){
 const canvas=$('village-canvas'),container=$('scene-wrap');
 const renderer=new T.WebGLRenderer({canvas,antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;renderer.setClearColor('#e9eee3');
 renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
 const scene=new T.Scene();scene.background=new T.Color('#e9eee3');
 const toys=createToyModels(T);addToyStudio(T,renderer,scene);
 const camera=new T.OrthographicCamera(-15,15,11,-11,.1,100);let yaw=Math.PI/4,zoomValue=1,elapsed=0,lastTime=0,drag=null,available=true,hovered=null,lastHover=-1;
 const materials=new Map();const boxGeometry=new T.BoxGeometry(1,1,1),studGeometry=new T.CylinderGeometry(.135,.135,.075,16),sphereGeometry=new T.SphereGeometry(1,12,8);
 function mat(color){if(!materials.has(color))materials.set(color,new T.MeshStandardMaterial({color,roughness:.72,metalness:0}));return materials.get(color);}
 function mesh(group,geometry,color,x,y,z,sx=1,sy=1,sz=1){const m=new T.Mesh(geometry,mat(color));m.position.set(x,y,z);m.scale.set(sx,sy,sz);m.castShadow=true;m.receiveShadow=true;group.add(m);return m;}
 function box(g,color,x,y,z,w,h,d){return mesh(g,boxGeometry,color,x,y,z,w,h,d);}
 function ball(g,color,x,y,z,r){return mesh(g,sphereGeometry,color,x,y,z,r,r,r);}

 scene.add(new T.HemisphereLight('#fff9e9','#77946d',1.4));
 const sun=new T.DirectionalLight('#fff4da',2.2);sun.position.set(-8,18,8);sun.castShadow=true;sun.shadow.mapSize.set(1536,1536);Object.assign(sun.shadow.camera,{left:-15,right:15,top:15,bottom:-15,near:.1,far:50});sun.shadow.bias=-.0005;sun.shadow.normalBias=.025;scene.add(sun);
 const island=new T.Group();scene.add(island);
 box(island,'#88a086',0,-.5,0,21,.65,21);box(island,'#afc2a3',0,-.12,0,20.7,.18,20.7);box(island,'#cddbc0',0,.01,0,20.3,.1,20.3);
 const studs=new T.InstancedMesh(studGeometry,mat('#c3d3b3'),1521),dummy=new T.Object3D();let n=0;
 for(let x=-9.5;x<=9.5;x+=.5)for(let z=-9.5;z<=9.5;z+=.5){dummy.position.set(x,.10,z);dummy.updateMatrix();studs.setMatrixAt(n++,dummy.matrix);}studs.receiveShadow=true;island.add(studs);
 // A perimeter walk leaves the priority placement area clear.
 for(const [x,z,w,d] of [[0,9,19,.65],[0,-9,19,.65],[9,0,.65,19],[-9,0,.65,19]])box(island,'#e5dfcd',x,.15,z,w,.1,d);
 function tree(g,x,z,scale=1){const a=toys.tree(x,z,scale);g.add(a);return a;}
 for(const [x,z,s] of [[-8,-6,1],[-6,-8,.85],[8,-6,.9],[7,8,1],[-8,6,.85],[5,-8,.75]])tree(island,x,z,s);
 for(const [x,z] of [[-8,3],[3,8]])toys.bench(island,x,z);
 const house=toys.home();house.position.y=.15;house.scale.setScalar(['start','location'].includes(mode)?1.65:1);scene.add(house);
 const models=new Map(),labels=new Map();
 function makeBlock(c){const g=toys.makeBlock(c);g.userData.category=c.id;g.position.y=.15;scene.add(g);models.set(c.id,g);
  const label=document.createElement('span');label.className='block-label';const text=document.createElement('span'),percentage=document.createElement('small');text.textContent=c.short;label.append(text,percentage);$('block-labels').append(label);labels.set(c.id,{label,percentage});
 }
 CATEGORIES.forEach(makeBlock);
 const guide=new T.Group();scene.add(guide);
 for(const radius of RADII){const points=Array.from({length:96},(_,i)=>new T.Vector3(Math.cos(i/96*Math.PI*2)*radius,.2,Math.sin(i/96*Math.PI*2)*radius));guide.add(new T.LineLoop(new T.BufferGeometry().setFromPoints(points),new T.LineBasicMaterial({color:'#4c8a67',transparent:true,opacity:.38})));}guide.visible=false;
 const highlight=mesh(scene,new T.TorusGeometry(.98,.025,5,48),'#f8efbf',0,.19,0);highlight.rotation.x=Math.PI/2;highlight.visible=false;highlight.castShadow=false;
 const bus=toys.bus('#e3ba72',true);scene.add(bus);
 const people=[];for(const [x,z,color] of [[-3,9,'#cb8872'],[9,5,'#8cabc0']]){const p=toys.person(color);p.scale.setScalar(.75);p.position.set(x,.2,z);scene.add(p);people.push(p);}
 const raycaster=new T.Raycaster(),pointer=new T.Vector2(),floor=new T.Plane(new T.Vector3(0,1,0),-.15),point=new T.Vector3();
 function updateCamera(){const r=27;camera.position.set(Math.sin(yaw)*r,24,Math.cos(yaw)*r);camera.lookAt(0,0,0);camera.zoom=zoomValue;camera.updateProjectionMatrix();camera.updateMatrixWorld();}
 function resize(){const width=container.clientWidth,height=container.clientHeight;if(!width||!height||!available)return;const aspect=width/height,entry=['start','location'].includes(mode),mobile=width<740;
  const v=entry?(mobile?14/aspect:Math.max(17.5,26/aspect)):Math.max(15,(mobile?14:18)/aspect),offset=entry&&!mobile?.22:0,verticalOffset=entry&&mobile?-v*.13:0;
  camera.left=-v*aspect/2+v*aspect*offset;camera.right=v*aspect/2+v*aspect*offset;camera.top=v/2+verticalOffset;camera.bottom=-v/2+verticalOffset;
  if(canvas.width!==Math.floor(width*renderer.getPixelRatio())||canvas.height!==Math.floor(height*renderer.getPixelRatio()))renderer.setSize(width,height,false);updateCamera();draw();}
 function sync(){
  const percentages=shares(draft.blocks);
  for(const c of CATEGORIES){const g=models.get(c.id),b=draft.blocks.find(v=>v.id===c.id),item=labels.get(c.id);g.visible=!!b&&mode==='town';item.label.hidden=!g.visible;
   if(b){g.position.x=b.x;g.position.z=b.z;item.percentage.textContent=c.id==='housing'?'참고':percentages[c.id]+'%';item.label.classList.toggle('active',draft.focus===c.id);}}
  const selected=draft.blocks.find(b=>b.id===draft.focus);highlight.visible=!!selected&&!['start','location'].includes(mode);if(selected)highlight.position.set(selected.x,.2,selected.z);
  guide.visible=!!drag?.id;resize();
 }
 function hit(event){const b=canvas.getBoundingClientRect();pointer.set((event.clientX-b.left)/b.width*2-1,-(event.clientY-b.top)/b.height*2+1);raycaster.setFromCamera(pointer,camera);}
 function floorPoint(event){hit(event);return raycaster.ray.intersectPlane(floor,point);}
 function findBlock(event){hit(event);const intersection=raycaster.intersectObjects([...models.values()].filter(g=>g.visible),true)[0];if(!intersection)return null;let object=intersection.object;while(object&&!object.userData.category)object=object.parent;return object?.userData.category||null;}
 function cancelDrag(){if(drag?.id){const b=draft.blocks.find(b=>b.id===drag.id);if(b)Object.assign(b,drag.before);}drag=null;guide.visible=false;canvas.style.cursor='';sync();}
 canvas.addEventListener('pointerdown',event=>{
  if(mode!=='town'||event.button!==0||drag)return;const id=findBlock(event),p=floorPoint(event);
  if(id){const b=draft.blocks.find(b=>b.id===id);draft.focus=id;drag={id,before:{x:b.x,z:b.z},offset:p?{x:b.x-p.x,z:b.z-p.z}:{x:0,z:0},pointer:event.pointerId};}
  else drag={id:null,lastX:event.clientX,pointer:event.pointerId};
  canvas.setPointerCapture(event.pointerId);canvas.style.cursor=id?'grabbing':'ew-resize';render();event.preventDefault();
 });
 canvas.addEventListener('pointermove',event=>{
  if(!drag){if(mode==='town'&&elapsed-lastHover>.08){lastHover=elapsed;hovered=findBlock(event);canvas.style.cursor=hovered?'grab':'ew-resize';}return;}
  if(drag.pointer!==event.pointerId)return;
  if(drag.id){const p=floorPoint(event);if(p&&moveBlock(draft,drag.id,p.x+drag.offset.x,p.z+drag.offset.z)){draft.handoff=false;render();}}
  else{yaw-=(event.clientX-drag.lastX)*.008;drag.lastX=event.clientX;updateCamera();draw();expose();}
 });
 canvas.addEventListener('pointerleave',()=>{if(!drag){hovered=null;canvas.style.cursor='';}});
 function finishDrag(event){if(!drag||drag.pointer!==event.pointerId)return;const id=drag.id;drag=null;guide.visible=false;canvas.style.cursor='';if(id)models.get(id).userData.landed=elapsed;save();render();if(id){const b=draft.blocks.find(b=>b.id===id);status(`${CATEGORIES.find(c=>c.id===id).label} · 중요도 ${6-levelForPosition(b.x,b.z)}/5`);}}
 canvas.addEventListener('pointerup',finishDrag);canvas.addEventListener('pointercancel',()=>{cancelDrag();render();});canvas.addEventListener('lostpointercapture',event=>{if(drag&&drag.pointer===event.pointerId){cancelDrag();render();}});
 canvas.addEventListener('wheel',event=>{if(mode!=='town')return;event.preventDefault();zoomValue=Math.min(2.8,Math.max(.8,zoomValue*Math.exp(-event.deltaY*.001)));updateCamera();draw();},{passive:false});
 function draw(){
  if(container.hidden||!available)return;
  renderer.render(scene,camera);const width=container.clientWidth,height=container.clientHeight;
  for(const c of CATEGORIES){const g=models.get(c.id),item=labels.get(c.id);if(!g.visible)continue;const p=new T.Vector3(g.position.x,g.position.y+(g.userData.labelHeight||2.15),g.position.z).project(camera);const x=(p.x+1)/2*width,y=(1-p.y)/2*height;item.label.style.left=x+'px';item.label.style.top=y+'px';item.label.hidden=x<35||x>width-35||y<20||y>height-40;}
 }
 function advance(dt){elapsed+=dt;if(motion){const t=elapsed*.17%4;if(t<1){bus.position.set(-8+t*16,.35,9);bus.rotation.y=0;}else if(t<2){bus.position.set(9,.35,9-(t-1)*17);bus.rotation.y=Math.PI/2;}else if(t<3){bus.position.set(9-(t-2)*17,.35,-9);bus.rotation.y=Math.PI;}else{bus.position.set(-9,.35,-9+(t-3)*17);bus.rotation.y=-Math.PI/2;}people[0].position.x=-3+Math.sin(elapsed*.3)*1.2;people[1].position.z=5+Math.sin(elapsed*.25)*.9;}
  const blend=motion?1-Math.exp(-dt*18):1,targetHouse=['start','location'].includes(mode)?1.65:1;house.scale.setScalar(T.MathUtils.lerp(house.scale.x,targetHouse,blend));
  for(const [id,g] of models){const held=drag?.id===id,age=elapsed-(g.userData.landed??-10),bounce=motion&&age<.8?Math.sin(age*17)*Math.exp(-age*8)*.16:0;
   g.position.y=T.MathUtils.lerp(g.position.y,.15+(held?.42:Math.max(0,bounce)),blend);const scale=held?1.045:hovered===id?1.018:1;g.scale.setScalar(T.MathUtils.lerp(g.scale.x,scale,blend));
   g.rotation.x=T.MathUtils.lerp(g.rotation.x,held?-.045:0,blend);g.rotation.z=T.MathUtils.lerp(g.rotation.z,held?.035:0,blend);
  }draw();}
 function loop(time){if(!document.hidden&&!container.hidden&&available)advance(Math.min((time-lastTime)/1000,.05));lastTime=time;requestAnimationFrame(loop);}
 new ResizeObserver(resize).observe(container);document.addEventListener('fullscreenchange',resize);
 canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();cancelDrag();available=false;$('fallback-note').hidden=false;render();status('3D 연결이 끊겼어. 화면을 새로고침해 봐.');});
 updateCamera();sync();requestAnimationFrame(loop);
 return {sync,cancelDrag,advance,get available(){return available;},get yaw(){return yaw;},get dragId(){return drag?.id||null;},rotate(amount){if(drag)return;yaw+=amount;updateCamera();draw();expose();},zoom(factor){zoomValue=Math.min(2.8,Math.max(.8,zoomValue*factor));updateCamera();draw();}};
}
