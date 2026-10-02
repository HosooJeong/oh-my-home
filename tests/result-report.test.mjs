import test from 'node:test';
import assert from 'node:assert/strict';
import {categoryReports,radarGeometry,researchNotes,criterionReason} from '../app/static/result-report.mjs';
import {candidateViews,profileWeights} from '../app/static/analysis-view.mjs';
const criterion=(id,group,importance=1)=>({id,group_id:group,module_id:group,label:id,need:id,importance,utility:{direction:'lower',ideal:500,limit:1500,unit:'m'},hard:null});
const profile=()=>({groups:[{id:'living',label:'생활',weight:80},{id:'education',label:'교육',weight:20},{id:'housing',label:'비용',weight:0}],criteria:[criterion('mart','living'),criterion('clinic','living',3),criterion('school','education')],questions:[],context:[]});
function views(p,values){
 const weights=profileWeights(p),evidence=[],assessments=[];
 for(const [id,measurements] of Object.entries(values)){
  const details=p.criteria.map(c=>{const value=measurements[c.id],known=value!==null&&value!==undefined,eid=id+'_'+c.id;evidence.push({id:eid,candidate_id:id,criterion_id:c.id,value:known?value:null,unit:c.utility.unit,status:known?'verified':'missing',source_record:eid});return {criterion_id:c.id,evidence_id:eid,weight:weights[c.id],status:known?'known':'unknown',hard_status:c.hard?'unknown':'not_required'};});assessments.push({candidate_id:id,eligibility:'eligible',details});
 }
 return candidateViews(p,{modules:[{module_id:'living',status:'completed',evidence}],report:{assessments},facilities:{}},Object.keys(values).map(id=>({id,label:id})));
}
test('desired level is personal ideal 100, not priority; category fit uses original internal weights',()=>{
 const p=profile(),before=structuredClone(p),[view]=views(p,{a:{mart:500,clinic:1500,school:1000}}),report=categoryReports(p,view,['living','education','housing']);
 assert.equal(report[0].target,100);assert.equal(report[0].score,25);assert.equal(report[2].target,100);assert.equal(report[2].score,50);assert.equal(report[0].share,.8);assert.equal(report[2].share,.2);assert.equal(report[5].score,null);assert.equal(report[5].target,null);assert.deepEqual(p,before);
});
test('unknown internal weight remains in the denominator and cannot inflate a partial axis',()=>{
 const p=profile(),[view]=views(p,{a:{mart:500,clinic:null,school:500}}),report=categoryReports(p,view,['living','education']);
 assert.equal(report[0].score,null);assert.equal(report[0].coverage,.25);assert.deepEqual(report[0].range,[25,100]);assert.equal(report[0].status,'partial');
 const g=radarGeometry(report);assert.equal(g.complete,false);assert.equal(g.actual.length,0);assert.equal(g.axes[5].score,null);
});
test('verified zero stays at the centre; unselected and price reference axes remain empty',()=>{
 const p=profile(),[view]=views(p,{a:{mart:1500,clinic:1500,school:500}}),report=categoryReports(p,view,['living','education','housing']),g=radarGeometry(report);
 assert.equal(report[0].score,0);assert.deepEqual(g.point(0,report[0].score),[220,202]);assert.equal(report[3].status,'unselected');assert.equal(report[5].status,'reference');assert.equal(report[5].score,null);
});
test('candidate switch uses its own evidence, never the first candidate measurement',()=>{
 const p=profile(),v=views(p,{a:{mart:500,clinic:500,school:500},b:{mart:1500,clinic:1000,school:null}}),a=categoryReports(p,v[0],['living']),b=categoryReports(p,v[1],['living']);
 assert.equal(a[0].score,100);assert.equal(b[0].score,37.5);assert.equal(b[2].score,null);
});
test('unconfirmed zero-weight hard requirement stays visible and prevents a complete category verdict',()=>{
 const p=profile();p.criteria.push({...criterion('hard','living',0),hard:{operator:'lte',value:600}});const [v]=views(p,{a:{mart:500,clinic:500,school:500}}),r=categoryReports(p,v,['living']);
 assert.equal(r[0].score,null);assert.equal(r[0].hardUnknown.length,1);assert.deepEqual(r[0].range,[100,100]);
});
test('foreign or mismatched evidence is not drawn as verified fulfilment',()=>{
 const p=profile(),[v]=views(p,{a:{mart:500,clinic:500,school:500}});v.rows[0].known=false;v.rows[0].fit=null;const r=categoryReports(p,v,['living']);assert.equal(r[0].score,null);assert.ok(Math.abs(r[0].range[0]-75)<1e-9);assert.ok(Math.abs(r[0].range[1]-100)<1e-9);
});
test('price-only reference retains hard unknown and never synthesizes a house score',()=>{
 const p={groups:[{id:'housing',weight:0}],criteria:[{...criterion('budget','housing'),hard:{operator:'lte',value:4e8}}]},r=categoryReports(p,null,['housing']);assert.equal(r[5].score,null);assert.equal(r[5].hardUnknown.length,1);assert.equal(r[5].rows[0].reason,'집별 조건 미확인');
});
test('additional groups stay in the report while the hexagon keeps six fixed axes',()=>{
 const p=profile();p.groups.push({id:'extension',label:'추가 요소',weight:10});p.criteria.push(criterion('other','extension'));const [v]=views(p,{a:{mart:500,clinic:500,school:500,other:500}}),r=categoryReports(p,v,['extension']);assert.equal(r.length,7);assert.equal(r[6].score,100);assert.equal(radarGeometry(r).axes.length,6);
});
test('qualitative notes require category-bound request IDs and remain distinct from candidate scores',()=>{
 const requests=[{id:'living_r',module:'living'},{id:'school_r',module:'education'},{id:'safety_r',module:'safety'},{id:'hobby_r',module:'leisure',criterion_ids:['hobby']}],data={items:[{facility_id:'mart',excerpts:[{quote:'생활',request_ids:['living_r']},{quote:'학원',request_ids:['school_r']},{quote:'연결 없음'}]}],safety:{items:[{area_name:'지역',excerpts:[{quote:'안전',request_ids:['safety_r']}]}]},leisure:{discoveries:[{name:'후보',criterion_id:'hobby',note:'날짜 미확인',excerpts:[]},{name:'취미',excerpts:[{quote:'경험',request_ids:['hobby_r']}]}]}};
 assert.deepEqual(researchNotes(data,requests,'living').map(n=>n.excerpt?.quote),['생활']);assert.deepEqual(researchNotes(data,requests,'education').map(n=>n.excerpt?.quote),['학원']);assert.equal(researchNotes(data,requests,'safety')[0].kind,'area');assert.equal(researchNotes(data,requests,'leisure').length,2);assert.equal(researchNotes(data,requests,'housing').length,0);assert.equal(researchNotes(data,requests).length,6);
});
test('evaluation reason uses the candidate measurement and personal target, while missing stays undecided',()=>{
 const p=profile(),[v]=views(p,{a:{mart:800,clinic:200,school:null}});assert.match(criterionReason(v.rows[0]),/목표보다 300m 더 멀어/);assert.match(criterionReason(v.rows[1]),/목표 수준을 충족/);assert.match(criterionReason(v.rows[2]),/충족 여부는 미확인/);
});
