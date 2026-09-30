// Original procedural toy parts. Dimensions are virtual, unrelated to scoring.
export function createToyModels(T){
 const geometries=new Map(),materials=new Map();
 const cream='#f5ead4',white='#fff7e5',dark='#35483e',glass='#538c9b',gold='#dcb95e';
 function material(color,finish='plastic'){
  const key=color+finish;if(!materials.has(key))materials.set(key,new T.MeshPhysicalMaterial({color,
   roughness:finish==='rubber'?.83:finish==='glass'?.12:.29,metalness:finish==='metal'?.35:0,
   clearcoat:finish==='rubber'?0:.65,clearcoatRoughness:.2,envMapIntensity:finish==='rubber'?.12:.6}));
  return materials.get(key);
 }
 function cached(key,build){if(!geometries.has(key))geometries.set(key,build());return geometries.get(key);}
 function rounded(w,h,d){
  const r=Math.min(.035,w*.15,h*.15,d*.15);
  return cached(`box:${w}:${h}:${d}`,()=>{
   const g=new T.BoxGeometry(w,h,d,6,6,6),p=g.attributes.position,n=g.attributes.normal;
   for(let i=0;i<p.count;i++){
    const x=p.getX(i),y=p.getY(i),z=p.getZ(i);
    const ix=T.MathUtils.clamp(x,-w/2+r,w/2-r),iy=T.MathUtils.clamp(y,-h/2+r,h/2-r),iz=T.MathUtils.clamp(z,-d/2+r,d/2-r);
    const v=new T.Vector3(x-ix,y-iy,z-iz).normalize();p.setXYZ(i,ix+v.x*r,iy+v.y*r,iz+v.z*r);n.setXYZ(i,v.x,v.y,v.z);
   }return g;
  });
 }
 function part(g,geometry,color,x,y,z,rotation=[0,0,0],finish='plastic'){
  const m=new T.Mesh(geometry,material(color,finish));m.position.set(x,y,z);m.rotation.set(...rotation);m.castShadow=true;m.receiveShadow=true;g.add(m);return m;
 }
 function tile(g,color,x,y,z,w,h,d,rotation=[0,0,0],finish='plastic'){return part(g,rounded(w,h,d),color,x,y,z,rotation,finish);}
 function cylinder(g,color,x,y,z,r,h,rotation=[0,0,0],finish='plastic',top=r){
  return part(g,cached(`cyl:${r}:${top}:${h}`,()=>new T.CylinderGeometry(top,r,h,20)),color,x,y,z,rotation,finish);
 }
 function ring(g,color,x,y,z,r,t,rotation=[0,0,0],finish='plastic'){
  return part(g,cached(`ring:${r}:${t}`,()=>new T.TorusGeometry(r,t,6,24)),color,x,y,z,rotation,finish);
 }
 function stud(g,color,x,y,z){
  cylinder(g,color,x,y,z,.105,.075);ring(g,color,x,y+.034,z,.083,.012,[Math.PI/2,0,0]);
  // Raised molding detail on the stud, with no logo or brand inscription.
  tile(g,color,x,y+.04,z,.045,.007,.045);
 }
 function brick(g,color,x,y,z,nx=2,nz=2,height=.26,pitch=.34,studs=true){
  const w=nx*pitch-.018,d=nz*pitch-.018;tile(g,color,x,y,z,w,height-.014,d);
  if(studs)for(let ix=0;ix<nx;ix++)for(let iz=0;iz<nz;iz++)stud(g,color,x+(ix-(nx-1)/2)*pitch,y+height/2+.018,z+(iz-(nz-1)/2)*pitch);
 }
 function plate(g,color='#e0d8bc',nx=5,nz=5){brick(g,color,0,.105,0,nx,nz,.18,.34);}
 function wall(g,color,width,depth,rows=4){
  const step=width/4;
  for(let row=0;row<rows;row++){
   const y=.31+row*.245;
   // Staggered courses include half pieces instead of engraving one box.
   const cuts=row%2?[-width/2,-width/2+step/2,-width/2+step*1.5,-width/2+step*2.5,-width/2+step*3.5,width/2]:[-width/2,-width/2+step,-width/2+step*2,-width/2+step*3,width/2];
   for(let i=1;i<cuts.length;i++)for(const z of [-depth/2,depth/2])tile(g,color,(cuts[i]+cuts[i-1])/2,y,z,cuts[i]-cuts[i-1]-.015,.226,.12);
   for(const x of [-width/2,width/2])for(let i=0;i<3;i++)tile(g,color,x,y,-depth/2+(i+.5)*depth/3,.12,.226,depth/3-.015);
  }
 }
 function window(g,x,y,z,w=.32,h=.38,ry=0){
  const f=new T.Group();f.position.set(x,y,z);f.rotation.y=ry;g.add(f);
  tile(f,dark,0,0,0,w+.08,h+.08,.045);tile(f,glass,0,0,.033,w,h,.032,[0,0,0],'glass');
  for(const sx of [-1,1])tile(f,white,sx*(w/2+.012),0,.069,.038,h+.11,.07);
  for(const sy of [-1,1])tile(f,white,0,sy*(h/2+.014),.069,w+.11,.04,.07);
  tile(f,white,0,0,.079,.027,h,.025);tile(f,white,0,0,.079,w,.027,.025);
  tile(f,white,0,-h/2-.075,.087,w+.16,.075,.16);
  tile(f,'#aec9ce',-.065,h*.22,.058,.032,h*.28,.012,[0,0,-.45],'glass');
 }
 function door(g,x,z,h=.65){
  tile(g,dark,x,.27+h/2,z,.39,h+.07,.055);tile(g,'#8b6245',x,.27+h/2,z+.035,.32,h,.065);
  for(const y of [.38,.62])tile(g,'#a57b54',x,y,z+.078,.22,.16,.016);
  cylinder(g,gold,x+.1,.59,z+.13,.033,.032,[Math.PI/2,0,0],'metal');tile(g,cream,x,.25,z+.12,.48,.09,.28);
 }
 function flower(g,x,z,color='#df9b66'){
  cylinder(g,'#799365',x,.29,z,.025,.22);cylinder(g,'#947255',x,.2,z,.07,.14,[0,0,0],'plastic',.09);
  for(let i=0;i<5;i++){const a=i*Math.PI*2/5;cylinder(g,color,x+Math.cos(a)*.052,.43,z+Math.sin(a)*.052,.036,.025);}
  cylinder(g,gold,x,.445,z,.028,.025);
 }
 function roof(g,width,depth,y,color){
  // Two sloped tile assemblies, individual overlapping plates and ridge pieces.
  for(const side of [-1,1])for(let row=0;row<3;row++)for(let col=0;col<4;col++){
   const x=(col-1.5)*width/4,z=side*(row+.5)*depth/6,yy=y+(3-row)*.13;
   tile(g,color,x,yy,z,width/4-.012,.10,depth/6+.065,[side*.38,0,0]);
  }
  for(let i=0;i<4;i++)cylinder(g,'#bc6747',(i-1.5)*width/4,y+.48,0,.105,width/4-.012,[0,0,Math.PI/2]);
 }
 function tree(x=0,z=0,scale=1){
  const g=new T.Group();g.position.set(x,.18,z);g.scale.setScalar(scale);
  cylinder(g,'#987350',0,.5,0,.095,.88);brick(g,'#857c52',0,.12,0,2,2,.14);
  for(const [y,n,c] of [[.83,3,'#739471'],[1.08,3,'#83a67f'],[1.31,2,'#94b78f']])brick(g,c,0,y,0,n,n,.25);
  return finish(g);
 }
 function home(){
  const g=new T.Group();brick(g,'#d4c5a4',0,.12,0,7,6,.21,.32);
  wall(g,'#eed8b3',1.55,1.35,5);brick(g,cream,0,1.53,0,5,4,.13,.34);
  door(g,.24,.73,.72);window(g,-.42,1,.74,.32,.47);window(g,.78,1.02,-.2,.38,.47,Math.PI/2);
  window(g,-.78,1.02,-.15,.38,.47,-Math.PI/2);window(g,0,1.04,-.71,.4,.43,Math.PI);
  // Triangular gables are built from progressively narrower stacked bricks.
  for(const z of [-.65,.65])for(let row=0;row<3;row++)tile(g,'#f2dfbd',0,1.68+row*.15,z,1.3-row*.38,.145,.12);
  roof(g,1.98,1.7,1.68,'#d87952');
  for(let row=0;row<3;row++)brick(g,'#b57d61',.51,2.02+row*.19,-.28,1,1,.19,.3);
  tile(g,cream,.51,2.53,-.28,.4,.1,.4);tile(g,dark,.51,2.589,-.28,.2,.018,.2);
  for(let i=0;i<2;i++)tile(g,'#ddc8a0',.24,.18-i*.045,.93+i*.17,.64+i*.14,.12,.25);
  for(const x of [-.72,.7]){tile(g,'#b8996b',x,.26,.93,.42,.13,.3);flower(g,x-.08,1,'#cd7962');flower(g,x+.08,1,'#e6bd68');}
  // Fence studs, a tiny mailbox and a front doormat.
  for(const x of [-.95,1.0]){brick(g,white,x,.31,.18,1,3,.14,.22);for(let i=0;i<3;i++)tile(g,white,x,.5,-.05+i*.22,.055,.36,.055);tile(g,white,x,.55,.18,.07,.07,.6);}
  tile(g,'#c1916c',.24,.3,.88,.34,.015,.2);tile(g,'#6c8e86',.91,.51,.61,.26,.21,.17);tile(g,white,.91,.48,.71,.17,.02,.012);
  return finish(g);
 }
 function bus(color='#e3b653',small=false){
  const g=new T.Group();plate(g,'#c7beaa',5,3);
  brick(g,'#b08b42',0,.3,0,4,2,.16);brick(g,color,0,.62,0,4,2,.47);brick(g,cream,0,.91,0,4,2,.12);
  tile(g,'#e9d6a8',0,.98,0,1.25,.09,.58);
  for(const z of [-.37,.37]){
   for(const x of [-.43,-.11,.21]){tile(g,dark,x,.67,z,.28,.31,.035);tile(g,glass,x,.7,z+Math.sign(z)*.026,.24,.24,.025,[0,0,0],'glass');}
   tile(g,cream,.49,.58,z,.21,.5,.047);tile(g,glass,.49,.7,z+Math.sign(z)*.029,.14,.23,.02,[0,0,0],'glass');
   for(const x of [-.45,.45]){cylinder(g,dark,x,.35,z,.18,.11,[Math.PI/2,0,0],'rubber');cylinder(g,'#d0c7ae',x,.35,z+Math.sign(z)*.067,.095,.025,[Math.PI/2,0,0],'metal');cylinder(g,dark,x,.35,z+Math.sign(z)*.087,.033,.021,[Math.PI/2,0,0]);}
   tile(g,'#b68439',0,.45,z+Math.sign(z)*.01,1.25,.035,.021);
  }
  for(const x of [-.71,.71]){tile(g,glass,x,.73,0,.028,.24,.53,[0,0,0],'glass');tile(g,cream,x,.38,0,.04,.09,.67);for(const z of [-.22,.22])tile(g,x>0?'#f6eac3':'#c9745b',x,.5,z,.041,.1,.12);}
  for(const z of [-.44,.44])tile(g,dark,.57,.73,z,.12,.07,.1);
  stud(g,color,-.36,1.075,0);stud(g,color,.36,1.075,0);
  if(small){g.scale.setScalar(.62);return finish(g);}return g;
 }
 function bench(g,x,z){
  for(let i=0;i<3;i++)tile(g,'#bd9467',x,.37,z+(i-1)*.085,.54,.05,.07);
  for(const dx of [-.2,.2]){tile(g,dark,x+dx,.25,z,.05,.22,.25);tile(g,dark,x+dx,.51,z-.1,.035,.36,.04);}
  for(const y of [.5,.59])tile(g,'#bd9467',x,y,z-.115,.54,.06,.045);
 }
 function person(color){
  const g=new T.Group();
  for(const x of [-.072,.072]){tile(g,dark,x,.16,0,.125,.25,.13);tile(g,dark,x,.055,.04,.13,.09,.22);cylinder(g,color,x,.19,.07,.03,.018,[Math.PI/2,0,0]);}
  tile(g,color,0,.405,0,.29,.31,.18);tile(g,'#e4bd8e',0,.59,0,.1,.06,.11);
  cylinder(g,'#e4bd8e',0,.71,0,.123,.21);cylinder(g,'#7b654b',0,.83,0,.135,.08);stud(g,'#7b654b',0,.88,0);
  for(const s of [-1,1]){cylinder(g,color,s*.2,.41,0,.055,.25,[0,0,s*.25]);ring(g,'#e4bd8e',s*.23,.26,.03,.039,.02,[Math.PI/2,0,0]);cylinder(g,dark,s*.044,.737,.125,.011,.012,[Math.PI/2,0,0]);}
  tile(g,dark,0,.683,.123,.053,.009,.015);tile(g,cream,0,.39,.098,.11,.1,.012);
  return finish(g);
 }
 function makeBlock(c){
  if(c.id==='transport'){const g=bus(c.color);return finish(g);}
  const g=new T.Group();plate(g);
  if(c.id==='living'){
   wall(g,'#f5e0bf',1.22,1.08,4);brick(g,c.color,0,1.27,0,4,4,.14);brick(g,cream,0,1.45,-.16,4,3,.14);
   for(const x of [-.37,.37])window(g,x,.69,.59,.32,.48);door(g,0,.61,.63);
   for(let i=0;i<6;i++){const x=(i-2.5)*.205;tile(g,i%2?white:c.color,x,1.14,.64,.198,.105,.39,[-.16,0,0]);tile(g,i%2?white:c.color,x,1.09,.81,.198,.15,.045);}
   tile(g,c.color,0,1.68,-.1,.92,.29,.12);tile(g,white,0,1.69,-.027,.7,.17,.02);
   // Grocery crate, separate fruit studs and a small roof vent.
   tile(g,'#aa8055',.55,.33,.65,.25,.16,.22);for(const [x,z] of [[.5,.6],[.61,.6],[.55,.71]])cylinder(g,'#d7ab52',x,.43,z,.04,.052);
   brick(g,'#94a99d',.38,1.6,-.31,1,1,.16,.28);flower(g,-.6,.68);
  }else if(c.id==='education'){
   wall(g,'#e9dcc2',1.24,1.13,5);brick(g,c.color,0,1.54,0,4,4,.13);
   for(const y of [.7,1.15])for(const x of [-.4,.4])window(g,x,y,.61,.26,.27);
   door(g,0,.63,.62);window(g,.67,1,-.1,.4,.5,Math.PI/2);
   roof(g,1.49,1.42,1.57,c.color);
   // Clock tower: brick courses, circular bezel, face and raised hands.
   for(let i=0;i<2;i++)brick(g,cream,0,1.83+i*.21,-.2,2,2,.2,.28);
   cylinder(g,'#7b918f',0,2.04,.103,.20,.05,[Math.PI/2,0,0]);cylinder(g,white,0,2.04,.14,.166,.028,[Math.PI/2,0,0]);
   for(let i=0;i<4;i++){const a=i*Math.PI/2;tile(g,dark,Math.cos(a)*.124,2.04+Math.sin(a)*.124,.16,.024,.025,.015);}
   tile(g,dark,0,2.08,.168,.022,.12,.018);tile(g,dark,.041,2.04,.168,.095,.022,.018);
   brick(g,c.color,0,2.22,-.2,2,2,.1,.31);tile(g,dark,-.57,1.9,-.42,.026,.57,.026);tile(g,'#dfb965',-.43,2.06,-.42,.26,.16,.028);
   for(const x of [-.53,.53])flower(g,x,.73,'#d69a76');
  }else if(c.id==='safety'){
   wall(g,'#e9dfcf',1.12,1.04,4);brick(g,c.color,0,1.28,0,4,4,.13);brick(g,white,0,1.43,0,3,3,.14);
   window(g,-.32,.78,.56,.29,.42);door(g,.25,.57,.66);window(g,.62,.8,0,.36,.38,Math.PI/2);
   tile(g,c.color,0,1.47,.6,.85,.25,.08);tile(g,white,0,1.49,.651,.35,.04,.02);tile(g,white,0,1.49,.651,.04,.14,.02);
   cylinder(g,'#d8caab',-.25,1.54,0,.15,.1);cylinder(g,c.color,-.25,1.67,0,.12,.15,[0,0,0],'glass',.09);
   tile(g,dark,.65,.91,.55,.058,1.37,.058);tile(g,dark,.56,1.57,.55,.24,.06,.06);
   tile(g,white,.48,1.51,.55,.23,.17,.23);tile(g,gold,.48,1.41,.55,.15,.025,.15);brick(g,c.color,.61,.25,.48,1,1,.14,.25);
   tile(g,dark,-.56,.36,.73,.2,.18,.055);tile(g,gold,-.56,.36,.767,.13,.027,.02);
  }else if(c.id==='leisure'){
   brick(g,c.color,0,.25,0,5,5,.09);const t=tree(-.47,-.4,.61);g.add(t);
   // Table tennis table: two plates, raised edge, mesh-like net slats and paddle.
   for(const x of [.17,.59])tile(g,'#577e89',x,.58,.31,.40,.055,.66);
   for(const z of [-.035,.655])tile(g,white,.38,.613,z,.82,.012,.018);
   tile(g,white,.38,.613,.31,.018,.012,.65);
   for(const x of [.02,.75])tile(g,dark,x,.39,.31,.045,.35,.045);
   tile(g,white,.38,.68,.31,.025,.14,.68);for(let i=0;i<9;i++)tile(g,dark,.397,.69,.01+i*.075,.008,.13,.012);
   cylinder(g,'#bb7660',.61,.63,.5,.055,.017);tile(g,dark,.61,.628,.57,.028,.02,.07);
   bench(g,-.43,.49);flower(g,.65,-.64,'#dbbd69');
  }else if(c.id==='housing'){
   // A small key on a stepped stack of assembled bricks and coin plates.
   for(let row=0;row<4;row++)brick(g,row%2?cream:c.color,-.3,.35+row*.23,-.1,2,2,.22);
   for(const [x,z,n] of [[.42,.18,4],[.51,-.31,2]])for(let i=0;i<n;i++){cylinder(g,gold,x,.28+i*.09,z,.19,.08,[0,0,0],'metal');ring(g,'#efcf78',x,.326+i*.09,z,.153,.012,[Math.PI/2,0,0],'metal');}
   ring(g,gold,-.28,1.29,-.08,.17,.047,[Math.PI/2,0,0],'metal');tile(g,gold,-.28,1.29,.21,.085,.06,.39,[0,0,0],'metal');
   for(const z of [.29,.4])tile(g,gold,-.2,1.29,z,.17,.06,.07,[0,0,0],'metal');
   tile(g,'#91a79a',.35,.25,.55,.47,.03,.28);tile(g,cream,.35,.27,.55,.33,.012,.16);
  }
  return finish(g);
 }
 function finish(g){
  // Batch identical parts per assembly. Picking still resolves to its category root.
  g.updateMatrixWorld(true);const inv=g.matrixWorld.clone().invert(),batches=new Map(),originals=[];
  g.traverse(o=>{if(o.isMesh){const key=o.geometry.uuid+':'+o.material.uuid;if(!batches.has(key))batches.set(key,{geometry:o.geometry,material:o.material,matrices:[]});const base=new T.Matrix4().multiplyMatrices(inv,o.matrixWorld),matrices=batches.get(key).matrices;
   if(o.isInstancedMesh){const instance=new T.Matrix4();for(let i=0;i<o.count;i++){o.getMatrixAt(i,instance);matrices.push(new T.Matrix4().multiplyMatrices(base,instance));}}else matrices.push(base);originals.push(o);}});
  for(const o of originals)o.removeFromParent();
  for(const b of batches.values()){
   const m=new T.InstancedMesh(b.geometry,b.material,b.matrices.length);b.matrices.forEach((matrix,i)=>m.setMatrixAt(i,matrix));m.instanceMatrix.needsUpdate=true;m.castShadow=true;m.receiveShadow=true;m.computeBoundingBox();m.computeBoundingSphere();g.add(m);
  }
  g.userData.parts=originals.reduce((n,o)=>n+(o.isInstancedMesh?o.count:1),0);
  g.updateMatrixWorld(true);const bounds=new T.Box3().setFromObject(g),origin=new T.Vector3();g.getWorldPosition(origin);g.userData.labelHeight=bounds.max.y-origin.y+.26;
  return g;
 }
 return {home,makeBlock,tree,bus,bench,person};
}

export function addToyStudio(T,renderer,scene){
 // A small local lighting map supplies broad studio highlights on molded plastic.
 const width=128,height=64,data=new Float32Array(width*height*4);
 for(let y=0;y<height;y++)for(let x=0;x<width;x++){
  const u=x/width,v=y/height,soft=Math.exp(-Math.pow((u-.2)/.045,2)-Math.pow((v-.33)/.2,2))*2.6+Math.exp(-Math.pow((u-.7)/.14,2)-Math.pow((v-.28)/.14,2))*1.4;
  const i=(y*width+x)*4,ambient=.16+.34*(1-v);data[i]=ambient+soft;data[i+1]=ambient+soft*.96;data[i+2]=ambient+soft*.88;data[i+3]=1;
 }
 const texture=new T.DataTexture(data,width,height,T.RGBAFormat,T.FloatType);texture.mapping=T.EquirectangularReflectionMapping;texture.needsUpdate=true;
 const pmrem=new T.PMREMGenerator(renderer);const env=pmrem.fromEquirectangular(texture);scene.environment=env.texture;scene.environmentIntensity=.7;texture.dispose();pmrem.dispose();
 return env;
}
