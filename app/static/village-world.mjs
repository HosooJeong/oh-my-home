import {CATEGORIES,RADII,evaluationShares as shares,moveBlock,levelForPosition} from './village-model.mjs';
import {createToyModels,addToyStudio} from './village-models.mjs';

export function createVillageWorld(T,{canvas,container,labelsRoot,fallback,getDraft,getMode,onChange=()=>{},onSave=()=>{},onStatus=()=>{},onState=()=>{}}){
 const motion=!matchMedia('(prefers-reduced-motion: reduce)').matches;
 let presentation={mode:null,focus:null,statuses:{}},cameraTarget=new T.Vector3(),targetZoom=1,townZoom=1;
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
 const house=toys.home();house.position.y=.15;house.scale.setScalar(['start','location'].includes(getMode())?1.65:1);scene.add(house);
 const models=new Map(),labels=new Map();
 function makeBlock(c){const g=toys.makeBlock(c);g.traverse(o=>{if(o.isMesh)o.material=o.material.clone();});g.userData.category=c.id;g.position.y=.15;scene.add(g);models.set(c.id,g);
  const label=document.createElement('span');label.className='block-label';const text=document.createElement('span'),percentage=document.createElement('small');text.textContent=c.short;label.append(text,percentage);labelsRoot.append(label);labels.set(c.id,{label,percentage});
 }
 CATEGORIES.forEach(makeBlock);
 const guide=new T.Group();scene.add(guide);
 for(const radius of RADII){const points=Array.from({length:96},(_,i)=>new T.Vector3(Math.cos(i/96*Math.PI*2)*radius,.2,Math.sin(i/96*Math.PI*2)*radius));guide.add(new T.LineLoop(new T.BufferGeometry().setFromPoints(points),new T.LineBasicMaterial({color:'#4c8a67',transparent:true,opacity:.38})));}guide.visible=false;
 const highlight=mesh(scene,new T.TorusGeometry(.98,.025,5,48),'#f8efbf',0,.19,0);highlight.rotation.x=Math.PI/2;highlight.visible=false;highlight.castShadow=false;
 const bus=toys.bus('#e3ba72',true);scene.add(bus);
 const people=[];for(const [x,z,color] of [[-3,9,'#cb8872'],[9,5,'#8cabc0']]){const p=toys.person(color);p.scale.setScalar(.75);p.position.set(x,.2,z);scene.add(p);people.push(p);}
 const raycaster=new T.Raycaster(),pointer=new T.Vector2(),floor=new T.Plane(new T.Vector3(0,1,0),-.15),point=new T.Vector3();
 function updateCamera(){const r=27;camera.position.set(Math.sin(yaw)*r,24,Math.cos(yaw)*r);camera.position.add(cameraTarget);camera.lookAt(cameraTarget);camera.zoom=zoomValue;camera.updateProjectionMatrix();camera.updateMatrixWorld();}
 function resize(){const width=container.clientWidth,height=container.clientHeight;if(!width||!height||!available)return;const aspect=width/height,entry=['start','location'].includes(getMode()),mobile=width<740;
  const v=entry?(mobile?14/aspect:Math.max(17.5,26/aspect)):Math.max(15,(mobile?14:18)/aspect),offset=entry&&!mobile?.22:0,verticalOffset=entry&&mobile?-v*.13:0;
  camera.left=-v*aspect/2+v*aspect*offset;camera.right=v*aspect/2+v*aspect*offset;camera.top=v/2+verticalOffset;camera.bottom=-v/2+verticalOffset;
  if(canvas.width!==Math.floor(width*renderer.getPixelRatio())||canvas.height!==Math.floor(height*renderer.getPixelRatio()))renderer.setSize(width,height,false);updateCamera();draw();}
 function sync(){
  const percentages=shares(getDraft().blocks);
  for(const c of CATEGORIES){const g=models.get(c.id),b=getDraft().blocks.find(v=>v.id===c.id),item=labels.get(c.id);g.visible=!!b&&!['start','location'].includes(getMode());item.label.hidden=!g.visible;
   if(b){g.position.x=b.x;g.position.z=b.z;item.percentage.textContent=c.id==='housing'?'참고':percentages[c.id]+'%';item.label.classList.toggle('active',(getMode()==='town'?getDraft().focus:presentation.focus)===c.id);}}
  const selected=getDraft().blocks.find(b=>b.id===(presentation.focus||getDraft().focus));highlight.visible=!!selected&&!['start','location'].includes(getMode())&&!['results','reveal'].includes(presentation.mode);if(selected)highlight.position.set(selected.x,.2,selected.z);
  guide.visible=!!drag?.id;resize();
 }
 const beams=new T.Group();scene.add(beams);
 for(const c of CATEGORIES){const line=new T.Line(new T.BufferGeometry(),new T.LineBasicMaterial({color:c.color,transparent:true,opacity:0}));line.userData.category=c.id;const signal=new T.Mesh(new T.SphereGeometry(.11,8,6),new T.MeshBasicMaterial({color:c.color}));line.add(signal);line.userData.signal=signal;beams.add(line);}
 function present(value){if(presentation.mode==='town'&&value.mode!=='town')townZoom=zoomValue;if(value.mode==='town'&&presentation.mode!=='town')zoomValue=townZoom;presentation={...presentation,...value};sync();if(document.hidden)advance(10);}
 function hit(event){const b=canvas.getBoundingClientRect();pointer.set((event.clientX-b.left)/b.width*2-1,-(event.clientY-b.top)/b.height*2+1);raycaster.setFromCamera(pointer,camera);}
 function floorPoint(event){hit(event);return raycaster.ray.intersectPlane(floor,point);}
 function findBlock(event){hit(event);const intersection=raycaster.intersectObjects([...models.values()].filter(g=>g.visible),true)[0];if(!intersection)return null;let object=intersection.object;while(object&&!object.userData.category)object=object.parent;return object?.userData.category||null;}
 function cancelDrag(){if(drag?.id){const b=getDraft().blocks.find(b=>b.id===drag.id);if(b)Object.assign(b,drag.before);}drag=null;guide.visible=false;canvas.style.cursor='';sync();}
 canvas.addEventListener('pointerdown',event=>{
  if(getMode()!=='town'||event.button!==0||drag)return;const id=findBlock(event),p=floorPoint(event);
  if(id){const b=getDraft().blocks.find(b=>b.id===id);getDraft().focus=id;drag={id,before:{x:b.x,z:b.z},offset:p?{x:b.x-p.x,z:b.z-p.z}:{x:0,z:0},pointer:event.pointerId};}
  else drag={id:null,lastX:event.clientX,pointer:event.pointerId};
  canvas.setPointerCapture(event.pointerId);canvas.style.cursor=id?'grabbing':'ew-resize';onChange();event.preventDefault();
 });
 canvas.addEventListener('pointermove',event=>{
  if(!drag){if(getMode()==='town'&&elapsed-lastHover>.08){lastHover=elapsed;hovered=findBlock(event);canvas.style.cursor=hovered?'grab':'ew-resize';}return;}
  if(drag.pointer!==event.pointerId)return;
  if(drag.id){const p=floorPoint(event);if(p&&moveBlock(getDraft(),drag.id,p.x+drag.offset.x,p.z+drag.offset.z)){getDraft().handoff=false;onChange();}}
  else{yaw-=(event.clientX-drag.lastX)*.008;drag.lastX=event.clientX;updateCamera();draw();onState();}
 });
 canvas.addEventListener('pointerleave',()=>{if(!drag){hovered=null;canvas.style.cursor='';}});
 function finishDrag(event){if(!drag||drag.pointer!==event.pointerId)return;const id=drag.id;drag=null;guide.visible=false;canvas.style.cursor='';if(id)models.get(id).userData.landed=elapsed;onSave();onChange();if(id){const b=getDraft().blocks.find(b=>b.id===id);onStatus(`${CATEGORIES.find(c=>c.id===id).label} · 중요도 ${6-levelForPosition(b.x,b.z)}/5`);}}
 canvas.addEventListener('pointerup',finishDrag);canvas.addEventListener('pointercancel',()=>{cancelDrag();onChange();});canvas.addEventListener('lostpointercapture',event=>{if(drag&&drag.pointer===event.pointerId){cancelDrag();onChange();}});
 canvas.addEventListener('wheel',event=>{if(getMode()!=='town')return;event.preventDefault();zoomValue=Math.min(2.8,Math.max(.8,zoomValue*Math.exp(-event.deltaY*.001)));updateCamera();draw();},{passive:false});
 function draw(){
  if(container.hidden||!available)return;
  renderer.render(scene,camera);const width=container.clientWidth,height=container.clientHeight;
  for(const c of CATEGORIES){const g=models.get(c.id),item=labels.get(c.id);if(!g.visible)continue;const p=new T.Vector3(g.position.x,g.position.y+(g.userData.labelHeight||2.15),g.position.z).project(camera);const x=(p.x+1)/2*width,y=(1-p.y)/2*height;item.label.style.left=x+'px';item.label.style.top=y+'px';item.label.hidden=x<35||x>width-35||y<20||y>height-40;}
 }
 function advance(dt){elapsed+=dt;
  const stage=presentation.mode||getMode(),focus=presentation.focus||(stage==='detail'?getDraft().focus:null),selected=getDraft().blocks.find(b=>b.id===focus);
  const destination=selected&&['detail','questions'].includes(stage)?new T.Vector3(selected.x,.4,selected.z):['reveal','results'].includes(stage)?new T.Vector3(0,1,0):new T.Vector3();
  const cameraBlend=motion?1-Math.exp(-dt*5):1;
  cameraTarget.lerp(destination,cameraBlend);
  targetZoom=selected&&['detail','questions'].includes(stage)?1.75:['reveal','results'].includes(stage)?2:1;
  if(getMode()!=='town')zoomValue=T.MathUtils.lerp(zoomValue,targetZoom,cameraBlend);
  else cameraTarget.lerp(new T.Vector3(),cameraBlend);
  updateCamera();
  beams.visible=stage==='assemble';
  for(const line of beams.children){const b=getDraft().blocks.find(b=>b.id===line.userData.category);line.visible=!!b;if(b&&beams.visible){line.geometry.setFromPoints([new T.Vector3(b.x,1,b.z),new T.Vector3(0,1.3,0)]);line.material.opacity=.65;const travel=motion?(elapsed*1.6)%1:.5;line.userData.signal.position.set(b.x*(1-travel),1+.3*travel,b.z*(1-travel));}}
 if(motion){const t=elapsed*.17%4;if(t<1){bus.position.set(-8+t*16,.35,9);bus.rotation.y=0;}else if(t<2){bus.position.set(9,.35,9-(t-1)*17);bus.rotation.y=Math.PI/2;}else if(t<3){bus.position.set(9-(t-2)*17,.35,-9);bus.rotation.y=Math.PI;}else{bus.position.set(-9,.35,-9+(t-3)*17);bus.rotation.y=-Math.PI/2;}people[0].position.x=-3+Math.sin(elapsed*.3)*1.2;people[1].position.z=5+Math.sin(elapsed*.25)*.9;}
  const blend=motion?1-Math.exp(-dt*18):1,targetHouse=['start','location'].includes(getMode())?1.65:1;house.scale.setScalar(T.MathUtils.lerp(house.scale.x,targetHouse,blend));
  for(const [id,g] of models){const held=drag?.id===id,age=elapsed-(g.userData.landed??-10),bounce=motion&&age<.8?Math.sin(age*17)*Math.exp(-age*8)*.16:0;
   g.position.y=T.MathUtils.lerp(g.position.y,.15+(held?.42:Math.max(0,bounce)),blend);const scale=held?1.045:focus===id&&['detail','questions'].includes(stage)?1.09:hovered===id?1.018:1;g.scale.setScalar(T.MathUtils.lerp(g.scale.x,scale,blend));
   const progress=presentation.statuses[id],base={reading:.5,waiting:.27,running:.58,completed:1,partial:.78,failed:.36,cancelled:.36,not_executed:.27,unselected:.15}[progress]??1;
   const alpha=progress==='running'&&motion?base+.08*Math.sin(elapsed*3):base;
   g.userData.opacity=T.MathUtils.lerp(g.userData.opacity??1,alpha,cameraBlend);const opacity=g.userData.opacity;g.traverse(o=>{if(o.isMesh){const transparent=opacity<.99;if(o.material.transparent!==transparent){o.material.transparent=transparent;o.material.needsUpdate=true;}o.material.opacity=transparent?opacity*opacity:1;o.material.depthWrite=!transparent;o.castShadow=!transparent;}});
   g.rotation.x=T.MathUtils.lerp(g.rotation.x,held?-.045:0,blend);g.rotation.z=T.MathUtils.lerp(g.rotation.z,held?.035:0,blend);
  }draw();onState();}
 function loop(time){if(!document.hidden&&!container.hidden&&available)advance(Math.min((time-lastTime)/1000,.05));lastTime=time;requestAnimationFrame(loop);}
 new ResizeObserver(resize).observe(container);document.addEventListener('fullscreenchange',resize);
 canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();cancelDrag();available=false;fallback.hidden=false;onChange();onStatus('3D 연결이 끊겼어. 화면을 새로고침해 봐.');});
 updateCamera();sync();requestAnimationFrame(loop);
 return {sync,present,cancelDrag,advance,get available(){return available;},get pose(){return {zoom:zoomValue,target:cameraTarget.toArray(),opacity:Object.fromEntries([...models].filter(([,g])=>g.visible).map(([id,g])=>[id,g.userData.opacity??1]))};},get yaw(){return yaw;},get dragId(){return drag?.id||null;},rotate(amount){if(drag)return;yaw+=amount;updateCamera();draw();onState();},zoom(factor){zoomValue=Math.min(2.8,Math.max(.8,zoomValue*factor));updateCamera();draw();}};
}
