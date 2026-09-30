import {CATEGORIES,STORAGE_KEY,RADII,readDraft,shares,levelForPosition,toggleCategory,moveBlock,setLevel,buildRequest} from './village-model.mjs';

const $=id=>document.getElementById(id);
let draft;
try{draft=readDraft(sessionStorage.getItem(STORAGE_KEY));}catch{draft=readDraft(null);}
let mode=draft.entry?'town':'start',order=[],step=0,world=null;
let motion=!matchMedia('(prefers-reduced-motion: reduce)').matches;
const buttons=new Map();
const status=message=>$('village-status').textContent=message;
function save(){try{sessionStorage.setItem(STORAGE_KEY,JSON.stringify(draft));}catch{status('현재 화면에서는 입력 저장을 사용할 수 없어.');}}
function snapshot(){
 const percentages=shares(draft.blocks);
 return {mode,coordinate_system:'virtual floor: origin=home; X/Z horizontal; Y height; camera never changes priorities',focus:draft.focus,
  blocks:draft.blocks.map(b=>({...b,level:levelForPosition(b.x,b.z),share:percentages[b.id]})),camera_yaw:world?.yaw??null,dragging:world?.dragId??null,webgl:!!world,motion};
}
function expose(){const value=JSON.stringify(snapshot());$('scene-state').value=value;$('scene-state').textContent=value;}
window.render_game_to_text=()=>JSON.stringify(snapshot());
window.advanceTime=ms=>{if(world)world.advance(Math.max(0,Math.min(Number(ms)||0,10000))/1000);};

for(const c of CATEGORIES){
 const button=document.createElement('button');button.type='button';button.dataset.category=c.id;button.style.setProperty('--brick-color',c.color);
 const brick=document.createElement('span');brick.className='tray-brick';brick.setAttribute('aria-hidden','true');
 const name=document.createElement('span');name.className='tray-text';name.append(document.createTextNode(c.label));
 const share=document.createElement('small');name.append(share);button.append(brick,name);buttons.set(c.id,{button,share});$('category-tray').append(button);
 button.addEventListener('click',()=>{if(toggleCategory(draft,c.id)){draft.handoff=false;save();render();status('');}});
}
function render(){
 $('village-app').dataset.mode=mode;
 $('entry-panel').hidden=mode!=='start';$('location-panel').hidden=mode!=='location';
 $('town-tools').hidden=mode!=='town';$('detail-panel').hidden=!['detail','review'].includes(mode);
 $('question-view').hidden=mode!=='detail';$('review-view').hidden=mode!=='review';
 $('change-start').hidden=mode==='start';$('scene-controls').hidden=['start','location'].includes(mode);$('motion-toggle').hidden=['start','location'].includes(mode);
 $('location-title').textContent=draft.entry==='discover'?'어느 생활권에서 찾을까?':'어느 동네를 생각해?';
 $('location-label').textContent=draft.entry==='discover'?'진주 안에서 찾을 지역':'후보 주소·동네';
 $('location-input').value=draft.location;
 const percentages=shares(draft.blocks);
 $('selection-count').textContent=`카테고리 ${draft.blocks.length}/6`;
 for(const c of CATEGORIES){const {button,share}=buttons.get(c.id),active=draft.blocks.some(b=>b.id===c.id);button.setAttribute('aria-pressed',String(active));button.disabled=active&&draft.blocks.length===1;share.textContent=active?`${percentages[c.id]}%`:'추가';}
 const block=draft.blocks.find(b=>b.id===draft.focus),category=CATEGORIES.find(c=>c.id===draft.focus);
 $('selected-controls').hidden=!block;$('open-details').disabled=!draft.blocks.length;
 const picker=$('selected-name');picker.replaceChildren();
 for(const b of draft.blocks){const option=document.createElement('option');option.value=b.id;option.textContent=CATEGORIES.find(c=>c.id===b.id).label;picker.append(option);}picker.value=draft.focus||'';
 if(block){const level=levelForPosition(block.x,block.z);$('priority-level').value=level;$('priority-level').setAttribute('aria-valuetext',`${level}단계, 1이 가장 중요, 비중 ${percentages[block.id]}%`);$('selected-share').value=`${percentages[block.id]}%`;$('selected-share').textContent=`${percentages[block.id]}%`;$('closer').disabled=level===1;$('farther').disabled=level===5;$('selected-reference').hidden=block.id!=='housing';}
 $('motion-toggle').textContent=motion?'움직임 켜짐':'움직임 꺼짐';$('motion-toggle').setAttribute('aria-pressed',String(motion));
 if(mode==='detail'){
  const c=CATEGORIES.find(c=>c.id===order[step]);draft.focus=c.id;
  $('question-progress').textContent=`${step+1}/${order.length}`;$('question-category').textContent=c.label;$('question-label').textContent=c.question;
  $('question-mark').style.setProperty('--brick-color',c.color);$('category-answer').value=draft.answers[c.id]||'';$('category-answer').placeholder=c.placeholder;
  $('question-prev').disabled=step===0;$('question-next').textContent=step===order.length-1?'입력 확인':'다음';
 }else if(mode==='review'){
  $('question-progress').textContent=`${order.length}/${order.length}`;$('answer-summary').replaceChildren();
  for(const id of order){const c=CATEGORIES.find(c=>c.id===id),row=document.createElement('div');row.className='answer-item';const name=document.createElement('strong'),percent=document.createElement('span'),answer=document.createElement('p');name.textContent=c.label;percent.textContent=percentages[id]+'%';name.append(percent);answer.textContent=draft.answers[id]?.trim()||'아직 모르겠어';row.append(name,answer);$('answer-summary').append(row);}
 }
 world?.sync();expose();
}
document.querySelectorAll('[data-entry]').forEach(b=>b.addEventListener('click',()=>{draft.entry=b.dataset.entry;mode='location';save();render();}));
$('location-input').addEventListener('input',event=>{draft.location=event.target.value.slice(0,200);save();});
$('location-back').addEventListener('click',()=>{mode='start';render();});
$('change-start').addEventListener('click',()=>{mode='start';world?.cancelDrag();render();});
$('enter-town').addEventListener('click',()=>{mode='town';save();render();status(draft.blocks.length?'':'블록을 골라 집 주변에 놓아봐.');});
function changeLevel(level){if(setLevel(draft,draft.focus,level)){draft.handoff=false;save();render();status('');}}
$('selected-name').addEventListener('change',event=>{draft.focus=event.target.value;save();render();});
$('closer').addEventListener('click',()=>{const b=draft.blocks.find(b=>b.id===draft.focus);if(b)changeLevel(levelForPosition(b.x,b.z)-1);});
$('farther').addEventListener('click',()=>{const b=draft.blocks.find(b=>b.id===draft.focus);if(b)changeLevel(levelForPosition(b.x,b.z)+1);});
$('priority-level').addEventListener('input',event=>changeLevel(Number(event.target.value)));
$('open-details').addEventListener('click',()=>{if(!draft.blocks.length)return;order=draft.blocks.slice().sort((a,b)=>levelForPosition(a.x,a.z)-levelForPosition(b.x,b.z)).map(b=>b.id);step=0;mode='detail';world?.cancelDrag();status('');render();});
$('back-town').addEventListener('click',()=>{mode='town';render();});
$('category-answer').addEventListener('input',event=>{draft.answers[order[step]]=event.target.value.slice(0,450);draft.handoff=false;save();});
function nextQuestion(){if(step<order.length-1)step++;else mode='review';save();render();}
$('question-next').addEventListener('click',nextQuestion);
$('question-prev').addEventListener('click',()=>{step=Math.max(0,step-1);render();});
$('question-unknown').addEventListener('click',()=>{draft.answers[order[step]]='';nextQuestion();});
$('continue-workspace').addEventListener('click',()=>{draft.handoff=true;save();location.assign('/workspace');});
$('turn-left').addEventListener('click',()=>world?.rotate(-Math.PI/4));$('turn-right').addEventListener('click',()=>world?.rotate(Math.PI/4));
$('zoom-in').addEventListener('click',()=>world?.zoom(1.15));$('zoom-out').addEventListener('click',()=>world?.zoom(1/1.15));
$('motion-toggle').addEventListener('click',()=>{motion=!motion;render();});
document.addEventListener('keydown',event=>{if(event.key.toLowerCase()==='f'&&!['INPUT','TEXTAREA'].includes(event.target.tagName)){if(document.fullscreenElement)document.exitFullscreen?.();else $('scene-wrap').requestFullscreen?.();}});
render();

try{
 const THREE=await import('./vendor/three/three.module.min.js');
 world=createWorld(THREE);render();
}catch(error){$('fallback-note').hidden=false;console.warn('Village 3D unavailable:',error.message);expose();}

function createWorld(T){
 const canvas=$('village-canvas'),container=$('scene-wrap');
 const renderer=new T.WebGLRenderer({canvas,antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;renderer.setClearColor('#e5ecdf');
 renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.25;
 const scene=new T.Scene();scene.background=new T.Color('#e5ecdf');
 const camera=new T.OrthographicCamera(-15,15,11,-11,.1,100);let yaw=Math.PI/4,zoomValue=1,elapsed=0,lastTime=0,drag=null;
 const materials=new Map();const boxGeometry=new T.BoxGeometry(1,1,1),studGeometry=new T.CylinderGeometry(.12,.12,.085,12),sphereGeometry=new T.SphereGeometry(1,12,8);
 function mat(color){if(!materials.has(color))materials.set(color,new T.MeshStandardMaterial({color,roughness:.72,metalness:0}));return materials.get(color);}
 function mesh(group,geometry,color,x,y,z,sx=1,sy=1,sz=1){const m=new T.Mesh(geometry,mat(color));m.position.set(x,y,z);m.scale.set(sx,sy,sz);m.castShadow=true;m.receiveShadow=true;group.add(m);return m;}
 function box(g,color,x,y,z,w,h,d){return mesh(g,boxGeometry,color,x,y,z,w,h,d);}
 function ball(g,color,x,y,z,r){return mesh(g,sphereGeometry,color,x,y,z,r,r,r);}
 function brick(g,color,x,y,z,w,h,d,studs=true){const b=box(g,color,x,y,z,w,h,d);if(studs)for(const dx of [-w*.28,w*.28])for(const dz of [-d*.28,d*.28])mesh(g,studGeometry,color,x+dx,y+h/2+.035,z+dz);return b;}
 scene.add(new T.HemisphereLight('#fff9e9','#77946d',2.2));
 const sun=new T.DirectionalLight('#fff4da',3.2);sun.position.set(-8,18,8);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);Object.assign(sun.shadow.camera,{left:-15,right:15,top:15,bottom:-15,near:.1,far:50});sun.shadow.bias=-.0008;scene.add(sun);
 const island=new T.Group();scene.add(island);
 box(island,'#879d7a',0,-.5,0,21,.65,21);box(island,'#b0c3a0',0,-.12,0,20.7,.18,20.7);box(island,'#c5d2b3',0,.01,0,20.3,.1,20.3);
 const studs=new T.InstancedMesh(studGeometry,mat('#bdcdae'),169),dummy=new T.Object3D();let n=0;
 for(let x=-9;x<=9;x+=1.5)for(let z=-9;z<=9;z+=1.5){dummy.position.set(x,.105,z);dummy.scale.set(1,1,1);dummy.updateMatrix();studs.setMatrixAt(n++,dummy.matrix);}studs.receiveShadow=true;island.add(studs);
 // A perimeter walk leaves the priority placement area clear.
 for(const [x,z,w,d] of [[0,9,19,.65],[0,-9,19,.65],[9,0,.65,19],[-9,0,.65,19]])box(island,'#e5dfcd',x,.15,z,w,.1,d);
 function tree(g,x,z,scale=1){const a=new T.Group();a.position.set(x,.18,z);a.scale.setScalar(scale);g.add(a);box(a,'#9a8064',0,.48,0,.16,.95,.16);ball(a,'#78a281',0,1.1,0,.48);ball(a,'#92b496',.12,1.36,.02,.36);return a;}
 for(const [x,z,s] of [[-8,-6,1],[-6,-8,.85],[8,-6,.9],[7,8,1],[-8,6,.85],[5,-8,.75]])tree(island,x,z,s);
 for(const [x,z] of [[-8,3],[3,8]]){box(island,'#b88d69',x,.42,z,.9,.12,.38);for(const dx of [-.33,.33])box(island,'#717966',x+dx,.27,z,.08,.25,.32);box(island,'#b88d69',x,.62,z-.18,.9,.32,.07);}
 function home(){const g=new T.Group();brick(g,'#eae6d7',0,.15,0,2.3,.3,2.2);brick(g,'#fff5df',0,1,0,1.65,1.45,1.45,false);
  const roof=mesh(g,new T.ConeGeometry(1.35,.8,4),'#ce8161',0,2.06,0);roof.rotation.y=Math.PI/4;roof.scale.z=.9;
  box(g,'#97704e',.23,.65,.74,.38,.8,.06);ball(g,'#efd79d',.36,.64,.79,.04);
  for(const x of [-.47,.52]){box(g,'#7cafa7',x,1.25,.75,.35,.37,.06);box(g,'#fff9e8',x,1.25,.79,.035,.4,.035);}
  box(g,'#d9b07f',-.86,1.33,-.25,.06,.4,.5);brick(g,'#dca277',.44,2.08,-.26,.3,.58,.3);
  box(g,'#e4d9bb',0,.17,1.7,.8,.08,.8);tree(g,-1.4,.7,.5);g.position.y=.15;scene.add(g);return g;}
 const house=home();
 const models=new Map(),labels=new Map();
 function makeBlock(c){const g=new T.Group();g.userData.category=c.id;brick(g,'#f4eddf',0,.12,0,1.6,.24,1.5);
  if(c.id==='transport'){
   brick(g,c.color,0,.63,0,1.4,.75,.7);box(g,'#7099a0',0,.78,.36,1.15,.29,.025);for(const x of [-.45,.45])for(const z of [-.4,.4]){const wheel=mesh(g,new T.CylinderGeometry(.17,.17,.12,12),'#49594d',x,.3,z);wheel.rotation.x=Math.PI/2;}
  }else if(c.id==='leisure'){
   brick(g,c.color,0,.28,0,1.3,.1,1.2);tree(g,-.35,-.25,.6);box(g,'#7898a3',.32,.47,.32,.58,.07,.58);box(g,'#f1e4c5',.32,.57,.32,.6,.16,.035);box(g,'#697e73',.32,.33,.32,.1,.22,.1);
  }else if(c.id==='housing'){
   for(let i=0;i<3;i++)brick(g,i===1?'#d6bd9f':c.color,-.32,.38+i*.29,0,.55,.26,.7);
   const coin=mesh(g,new T.CylinderGeometry(.27,.27,.12,18),'#e2bd63',.38,.4,.18);coin.rotation.x=Math.PI/2;
   const key=mesh(g,new T.TorusGeometry(.2,.06,6,16),'#e6cb82',.3,.98,-.1);key.rotation.x=Math.PI/2;box(g,'#e6cb82',.3,.98,.2,.1,.1,.42);
  }else{
   brick(g,c.color,0,.7,0,1.16,.95,1);brick(g,c.id==='education'?'#e7dfcd':'#e5ddc7',0,1.25,0,1.35,.14,1.18);
   box(g,'#f8f0d9',0,.57,.51,.27,.65,.045);for(const x of [-.4,.4])box(g,'#819da0',x,.88,.51,.22,.29,.04);
   if(c.id==='living'){for(let i=0;i<5;i++)box(g,i%2?'#faead8':c.color,-.48+i*.24,1.15,.64,.24,.13,.5);box(g,'#f8eee1',0,1.66,0,.75,.45,.08);box(g,c.color,0,1.67,.05,.39,.07,.04);}
   if(c.id==='education'){box(g,c.color,0,1.58,0,.6,.5,.6);const clock=mesh(g,new T.CylinderGeometry(.18,.18,.035,16),'#fff6df',0,1.62,.32);clock.rotation.x=Math.PI/2;box(g,'#617680',0,1.69,.345,.025,.13,.02);box(g,'#617680',.06,1.62,.345,.13,.025,.02);}
   if(c.id==='safety'){box(g,'#737d69',.7,1,.3,.07,1.7,.07);box(g,'#eee7c7',.62,1.85,.3,.3,.18,.24);box(g,'#f8e4a6',.62,1.76,.3,.18,.07,.15);}
  }
  g.position.y=.15;scene.add(g);models.set(c.id,g);
  const label=document.createElement('span');label.className='block-label';const text=document.createElement('span'),percentage=document.createElement('small');text.textContent=c.short;label.append(text,percentage);$('block-labels').append(label);labels.set(c.id,{label,percentage});
 }
 CATEGORIES.forEach(makeBlock);
 const guide=new T.Group();scene.add(guide);
 for(const radius of RADII){const points=Array.from({length:96},(_,i)=>new T.Vector3(Math.cos(i/96*Math.PI*2)*radius,.2,Math.sin(i/96*Math.PI*2)*radius));guide.add(new T.LineLoop(new T.BufferGeometry().setFromPoints(points),new T.LineBasicMaterial({color:'#4c8a67',transparent:true,opacity:.38})));}guide.visible=false;
 const highlight=mesh(scene,new T.TorusGeometry(.98,.025,5,48),'#f8efbf',0,.19,0);highlight.rotation.x=Math.PI/2;highlight.visible=false;highlight.castShadow=false;
 const bus=new T.Group();brick(bus,'#e3ba72',0,.38,0,.8,.5,.4,false);box(bus,'#81999b',0,.46,.21,.6,.18,.025);scene.add(bus);
 const people=[];for(const [x,z,color] of [[-3,9,'#cb8872'],[9,5,'#8cabc0']]){const p=new T.Group();box(p,color,0,.35,0,.17,.3,.14);ball(p,'#e0bd95',0,.58,0,.11);for(const dx of [-.05,.05])box(p,'#5f756d',dx,.12,0,.05,.19,.05);p.position.set(x,.2,z);scene.add(p);people.push(p);}
 const raycaster=new T.Raycaster(),pointer=new T.Vector2(),floor=new T.Plane(new T.Vector3(0,1,0),-.15),point=new T.Vector3();
 function updateCamera(){const r=27;camera.position.set(Math.sin(yaw)*r,24,Math.cos(yaw)*r);camera.lookAt(0,0,0);camera.zoom=zoomValue;camera.updateProjectionMatrix();camera.updateMatrixWorld();}
 function resize(){const width=container.clientWidth,height=container.clientHeight,aspect=width/height,v=Math.max(22,30/aspect);const offset=['start','location'].includes(mode) ? .22 : 0;camera.left=-v*aspect/2+v*aspect*offset;camera.right=v*aspect/2+v*aspect*offset;camera.top=v/2;camera.bottom=-v/2;renderer.setSize(width,height,false);updateCamera();draw();}
 function sync(){
  const percentages=shares(draft.blocks);
  for(const c of CATEGORIES){const g=models.get(c.id),b=draft.blocks.find(v=>v.id===c.id),item=labels.get(c.id);g.visible=!!b;item.label.hidden=!b;
   if(b){g.position.x=b.x;g.position.z=b.z;item.percentage.textContent=percentages[c.id]+'%';item.label.classList.toggle('active',draft.focus===c.id);}}
  const selected=draft.blocks.find(b=>b.id===draft.focus);highlight.visible=!!selected&&!['start','location'].includes(mode);if(selected)highlight.position.set(selected.x,.2,selected.z);
  guide.visible=!!drag?.id;resize();
 }
 function hit(event){const b=canvas.getBoundingClientRect();pointer.set((event.clientX-b.left)/b.width*2-1,-(event.clientY-b.top)/b.height*2+1);raycaster.setFromCamera(pointer,camera);}
 function floorPoint(event){hit(event);return raycaster.ray.intersectPlane(floor,point);}
 function findBlock(event){hit(event);const intersection=raycaster.intersectObjects([...models.values()].filter(g=>g.visible),true)[0];if(!intersection)return null;let object=intersection.object;while(object&&!object.userData.category)object=object.parent;return object?.userData.category||null;}
 function cancelDrag(){if(drag?.id){const b=draft.blocks.find(b=>b.id===drag.id);if(b)Object.assign(b,drag.before);}drag=null;guide.visible=false;canvas.style.cursor='';sync();}
 canvas.addEventListener('pointerdown',event=>{
  if(mode!=='town'||event.button!==0)return;const id=findBlock(event),p=floorPoint(event);
  if(id){const b=draft.blocks.find(b=>b.id===id);draft.focus=id;drag={id,before:{x:b.x,z:b.z},offset:p?{x:b.x-p.x,z:b.z-p.z}:{x:0,z:0},pointer:event.pointerId};}
  else drag={id:null,lastX:event.clientX,pointer:event.pointerId};
  canvas.setPointerCapture(event.pointerId);canvas.style.cursor=id?'grabbing':'ew-resize';render();event.preventDefault();
 });
 canvas.addEventListener('pointermove',event=>{
  if(!drag||drag.pointer!==event.pointerId)return;
  if(drag.id){const p=floorPoint(event);if(p&&moveBlock(draft,drag.id,p.x+drag.offset.x,p.z+drag.offset.z)){draft.handoff=false;render();}}
  else{yaw-=(event.clientX-drag.lastX)*.008;drag.lastX=event.clientX;updateCamera();draw();expose();}
 });
 function finishDrag(event){if(!drag||drag.pointer!==event.pointerId)return;const id=drag.id;drag=null;guide.visible=false;canvas.style.cursor='';if(id)models.get(id).userData.landed=elapsed;save();render();if(id){const b=draft.blocks.find(b=>b.id===id);status(`${CATEGORIES.find(c=>c.id===id).label} · 중요도 ${6-levelForPosition(b.x,b.z)}/5`);}}
 canvas.addEventListener('pointerup',finishDrag);canvas.addEventListener('pointercancel',()=>{cancelDrag();render();});canvas.addEventListener('lostpointercapture',event=>{if(drag&&drag.pointer===event.pointerId){cancelDrag();render();}});
 canvas.addEventListener('wheel',event=>{if(mode!=='town')return;event.preventDefault();zoomValue=Math.min(1.5,Math.max(.8,zoomValue*Math.exp(-event.deltaY*.001)));updateCamera();draw();},{passive:false});
 function draw(){
  renderer.render(scene,camera);const width=container.clientWidth,height=container.clientHeight;
  for(const c of CATEGORIES){const g=models.get(c.id),item=labels.get(c.id);if(!g.visible)continue;const p=new T.Vector3(g.position.x,2.3,g.position.z).project(camera);const x=(p.x+1)/2*width,y=(1-p.y)/2*height;item.label.style.left=x+'px';item.label.style.top=y+'px';item.label.hidden=x<35||x>width-35||y<20||y>height-40;}
 }
 function advance(dt){elapsed+=dt;if(motion){const t=elapsed*.17%4;if(t<1){bus.position.set(-8+t*16,.35,9);bus.rotation.y=0;}else if(t<2){bus.position.set(9,.35,9-(t-1)*17);bus.rotation.y=Math.PI/2;}else if(t<3){bus.position.set(9-(t-2)*17,.35,-9);bus.rotation.y=Math.PI;}else{bus.position.set(-9,.35,-9+(t-3)*17);bus.rotation.y=-Math.PI/2;}people[0].position.x=-3+Math.sin(elapsed*.3)*1.2;people[1].position.z=5+Math.sin(elapsed*.25)*.9;}
  for(const [id,g] of models){const age=elapsed-(g.userData.landed??-10);const bounce=motion&&age<1 ? Math.abs(Math.sin(age*18))*Math.exp(-age*8)*.12 : 0;g.position.y=.15+(drag?.id===id ? .22 : bounce);}draw();}
 function loop(time){if(!document.hidden)advance(Math.min((time-lastTime)/1000,.05));lastTime=time;requestAnimationFrame(loop);}
 new ResizeObserver(resize).observe(container);document.addEventListener('fullscreenchange',resize);
 canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();$('fallback-note').hidden=false;status('3D 연결이 끊겼어. 아래 중요도 조절은 계속 사용할 수 있어.');});
 updateCamera();sync();requestAnimationFrame(loop);
 return {sync,cancelDrag,advance,get yaw(){return yaw;},get dragId(){return drag?.id||null;},rotate(amount){if(drag)return;yaw+=amount;updateCamera();draw();expose();},zoom(factor){zoomValue=Math.min(1.5,Math.max(.8,zoomValue*factor));updateCamera();draw();}};
}
