import test from 'node:test';
import assert from 'node:assert/strict';
import {CATEGORIES,RADII,emptyDraft,toggleCategory,moveBlock,setLevel,shares,evaluationShares,levelForPosition,readDraft,buildRequest,applyVillagePreferences,confirmAdditionalGroups} from '../app/static/village-model.mjs';

test('five distance levels are invariant under horizontal rotation',()=>{
 for(let i=0;i<RADII.length;i++)for(const angle of [0,.42,1.7,3.5])assert.equal(levelForPosition(Math.cos(angle)*RADII[i],Math.sin(angle)*RADII[i]),i+1);
 assert.throws(()=>levelForPosition(NaN,3));
});
test('displayed shares sum to 100% and a single block always has 100%',()=>{
 const d=emptyDraft();for(const c of CATEGORIES)toggleCategory(d,c.id);
 setLevel(d,'living',1);setLevel(d,'transport',2);setLevel(d,'housing',5);
 assert.equal(Math.round(Object.values(shares(d.blocks)).reduce((a,b)=>a+b,0)*10),1000);
 assert.equal(evaluationShares(d.blocks).housing,0);
 assert.equal(Math.round(Object.values(evaluationShares(d.blocks)).reduce((a,b)=>a+b,0)*10),1000);
 for(const c of CATEGORIES.slice(1))toggleCategory(d,c.id);
 assert.equal(d.blocks.length,1);assert.equal(shares(d.blocks).living,100);assert.equal(toggleCategory(d,'living'),false);
});
test('six close blocks fit without collisions and retain the requested band',()=>{
 const d=emptyDraft();for(const c of CATEGORIES)toggleCategory(d,c.id);
 for(const c of CATEGORIES)assert.equal(setLevel(d,c.id,1),true);
 for(const a of d.blocks){assert.equal(levelForPosition(a.x,a.z),1);for(const b of d.blocks)if(a!==b)assert.ok(Math.hypot(a.x-b.x,a.z-b.z)>=1.9);}
});
test('placement clamps boundaries and rejects nonfinite input without changing the draft',()=>{
 const d=emptyDraft();toggleCategory(d,'living');moveBlock(d,'living',0,0);assert.ok(Math.hypot(d.blocks[0].x,d.blocks[0].z)>=2);
 moveBlock(d,'living',100,100);assert.ok(Math.hypot(d.blocks[0].x,d.blocks[0].z)<=7.9);
 const before=structuredClone(d);assert.equal(moveBlock(d,'living',NaN,1),false);assert.deepEqual(d,before);
});
test('saved drafts preserve answers through deselection and reject corrupt/duplicate categories',()=>{
 const d=emptyDraft();d.entry='known';toggleCategory(d,'living');toggleCategory(d,'education');d.answers.education='영어 학원';toggleCategory(d,'education');
 const restored=readDraft(JSON.stringify(d));toggleCategory(restored,'education');assert.equal(restored.answers.education,'영어 학원');
 assert.deepEqual(readDraft('{bad'),emptyDraft());
 const invalid=readDraft(JSON.stringify({...d,blocks:[{id:'living',x:3,z:3},{id:'living',x:5,z:5},{id:'unknown',x:3,z:4}]}));assert.equal(invalid.blocks.length,1);
});
test('handoff stays below the intake limit and includes only selected answers',()=>{
 const d=emptyDraft();d.entry='discover';d.location='가'.repeat(200);for(const c of CATEGORIES){toggleCategory(d,c.id);d.answers[c.id]='나'.repeat(450);}
 assert.ok(buildRequest(d).length<4000);toggleCategory(d,'education');assert.ok(!buildRequest(d).includes('교육·육아:'));assert.ok(buildRequest(d).includes('가격 점수/실제 매물 추천은 제외'));
});
test('handoff preserves additional needs and chosen weights, with price reference-only',()=>{
 const d=emptyDraft();for(const id of ['living','transport','housing'])toggleCategory(d,id);setLevel(d,'living',1);setLevel(d,'transport',5);
 const p={groups:CATEGORIES.map(c=>({id:c.id,weight:50,source:'proposed'})),criteria:CATEGORIES.map(c=>({id:c.id+'-criterion',group_id:c.id,importance:100})),questions:[{id:'e',criterion_ids:['education-criterion']},{id:'t',criterion_ids:['transport-criterion']}]};
 const result=applyVillagePreferences(p,d);assert.equal(result.profile.groups.find(g=>g.id==='living').weight,100);assert.equal(result.profile.groups.find(g=>g.id==='transport').weight,20);assert.equal(result.profile.groups.find(g=>g.id==='housing').weight,0);assert.equal(result.profile.groups.length,6);assert.deepEqual(result.profile.questions,p.questions);assert.deepEqual(result.additionalGroups,['education','safety','leisure']);assert.equal(p.groups[0].weight,50);
});

test('an extension hard need and its question survive until explicit exclusion',()=>{
 const d=emptyDraft();toggleCategory(d,'education');
 const p={revision:1,request:'학교가 가까워야 하고 엘리베이터는 필수야.',context:[],groups:[{id:'education',weight:100,label:'교육'},{id:'accessibility',weight:25,label:'접근성'}],criteria:[{id:'school',group_id:'education',importance:100},{id:'lift',group_id:'accessibility',importance:0,hard:{operator:'eq',value:1}}],questions:[{id:'lift_check',criterion_ids:['lift'],blocking:true},{id:'both',criterion_ids:['lift','school'],blocking:false}]};
 const bridged=applyVillagePreferences(p,d);assert.deepEqual(bridged.profile.criteria,p.criteria);assert.deepEqual(bridged.profile.questions,p.questions);
 const kept=confirmAdditionalGroups(bridged.profile,bridged.additionalGroups,['accessibility']);assert.deepEqual(kept.criteria,p.criteria);assert.equal(kept.groups[1].source,'user');
 const excluded=confirmAdditionalGroups(bridged.profile,bridged.additionalGroups,[]);assert.deepEqual(excluded.criteria.map(c=>c.id),['school']);assert.deepEqual(excluded.questions.map(q=>q.criterion_ids),[['school']]);assert.ok(excluded.request.includes('제외'));assert.deepEqual(p.criteria[1].hard,{operator:'eq',value:1});
 assert.throws(()=>confirmAdditionalGroups(p,['accessibility'],['other']));
});
test('missing selected categories and reference-only profiles are explicit',()=>{
 const d=emptyDraft();toggleCategory(d,'living');assert.deepEqual(applyVillagePreferences({groups:[],criteria:[],questions:[]},d).missing,['living']);
 assert.deepEqual(applyVillagePreferences({groups:[{id:'living',weight:0}],criteria:[{group_id:'living',importance:0}],questions:[]},d).missing,['living']);
 const price=emptyDraft();toggleCategory(price,'housing');assert.equal(applyVillagePreferences({groups:[{id:'housing',weight:100}],criteria:[],questions:[]},price).referenceOnly,true);
});
test('three entries remain distinct and private house notes stay out of model input',()=>{
 for(const entry of ['discover','single','multiple']){const d=emptyDraft();d.entry=entry;d.location='개인 집 메모';toggleCategory(d,'living');assert.equal(readDraft(JSON.stringify(d)).entry,entry);assert.equal(buildRequest(d).includes('개인 집 메모'),entry==='discover');}
 const old=emptyDraft();old.entry='known';assert.equal(readDraft(JSON.stringify(old)).entry,'multiple');
 const price=emptyDraft();toggleCategory(price,'housing');const result=applyVillagePreferences({groups:[{id:'housing',weight:0}],criteria:[],questions:[]},price);assert.ok(result.profile);assert.equal(result.referenceOnly,true);
});
