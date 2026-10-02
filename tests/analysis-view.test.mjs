import test from 'node:test';
import assert from 'node:assert/strict';
import {profileWeights,profileView,confirmReviewedProfile,housingQueryProfile,candidateViews,researchCounts,measure} from '../app/static/analysis-view.mjs';

const criterion=(id,group='living',overrides={})=>({id,group_id:group,module_id:group,label:id,need:id+' 원문',source_quote:id+' 원문',source:'proposed',importance:1,importance_source:'proposed',metric:'distance',utility:{direction:'lower',ideal:500,limit:1500,unit:'m'},hard:null,...overrides});
function profile(){return {revision:1,request:'합성 조건',context:[],groups:[{id:'living',label:'생활',weight:60,source:'user'},{id:'education',label:'교육',weight:40,source:'proposed'}],criteria:[criterion('mart'),criterion('school','education')],questions:[]};}
const places=[{id:'a',label:'집 A'},{id:'b',label:'집 B'}];
test('app proposal uses plain preference labels and keeps numeric basis in details',()=>{
 const p=profile(),c=p.criteria[0];c.parameters={};c.comparison_proposal={label:'가까우면 좋아요',utility:{...c.utility},radius_m:null};
 const view=profileView(p).groups[0].criteria[0];assert.match(view.rule,/가까우면.*제안/);assert.doesNotMatch(view.rule,/500|1500/);assert.match(view.ruleDetail,/서비스 제안.*500.*1,500/);
 c.utility.limit=2000;assert.equal(profileView(p).groups[0].criteria[0].ruleDetail,null);
 assert.match(profileView(p).groups[0].criteria[0].rule,/2,000/);
});
function run(p,values){
 const weights=profileWeights(p),evidence=[],assessments=[];
 for(const place of places){const details=p.criteria.map(c=>{const value=values[place.id]?.[c.id],known=value!==null&&value!==undefined,id=place.id+'_'+c.id;
  evidence.push({id,candidate_id:place.id,criterion_id:c.id,value:known?value:null,unit:c.utility.unit,status:known?'verified':'missing',source_record:id,source_url:'https://example.invalid/public',data_date:'2026-10-01'});
  return {criterion_id:c.id,evidence_id:id,weight:weights[c.id],status:!weights[c.id]&&!c.hard?'not_requested':known?'known':'unknown',hard_status:c.hard?(known?'pass':'unknown'):'not_required'};});
  assessments.push({candidate_id:place.id,eligibility:'eligible',details});
 }
 return {report:{assessments},modules:[{module_id:'living',status:'completed',evidence,unsupported_criterion_ids:[]}],facilities:{},references:[]};
}
test('review shows actual overall shares, original need and zero-weight housing hard limit',()=>{
 const p=profile();p.criteria[0].importance=3;p.criteria.push(criterion('extra','living'));p.groups.push({id:'housing',weight:0});p.criteria.push(criterion('budget','housing',{hard:{operator:'lte',value:400000000},utility:{direction:'lower',ideal:300000000,limit:500000000,unit:'KRW'}}));
 const v=profileView(p);assert.equal(v.groups[0].criteria[0].share,'45.0%');assert.equal(v.groups[0].criteria[1].share,'15.0%');assert.equal(v.groups[1].criteria[0].share,'40.0%');assert.match(v.groups[2].criteria[0].hardLabel,/필수.*40,000만원.*이하/);assert.equal(v.groups[2].criteria[0].share,'0.0%');
});
test('confirmation preserves optional questions, hard limits and inactive proposed conditions without mutating input',()=>{
 const p=profile();p.criteria[0].hard={operator:'lte',value:900};p.criteria[0].source='user';p.criteria.push(criterion('inactive','living',{importance:0}));p.questions=[{id:'optional',blocking:false,text:'추가 맥락?',criterion_ids:['mart']}];const before=structuredClone(p);
 const confirmed=confirmReviewedProfile(p,JSON.stringify(p));assert.deepEqual(p,before);assert.deepEqual(confirmed.questions,p.questions);assert.deepEqual(confirmed.criteria[0].hard,p.criteria[0].hard);assert.equal(confirmed.criteria[2].source,'proposed');assert.equal(confirmed.criteria[1].source,'user');assert.equal(confirmed.criteria[1].importance_source,'user');assert.equal(confirmed.criteria[1].importance_proposal,1);assert.equal(confirmed.revision,2);
});
test('blocking interview and stale review cannot approve analysis',()=>{
 const p=profile(),snapshot=JSON.stringify(p);p.criteria[0].importance=2;assert.throws(()=>confirmReviewedProfile(p,snapshot),/바뀌었어/);p.questions=[{blocking:true}];assert.throws(()=>confirmReviewedProfile(p),/먼저/);
});
test('price-only hard needs remain in reviewed state while reference query carries original filters',()=>{
 const p={...profile(),groups:[{id:'housing',label:'비용',weight:0,source:'user'}],criteria:[criterion('budget','housing',{hard:{operator:'lte',value:400000000}})],context:[{key:'housing_legal_area',value:'평거동',source_quote:'평거동 거래 참고'},{key:'housing_budget',value:'4억원',source_quote:'예산 4억원 필수'}],questions:[{id:'optional',blocking:false,criterion_ids:['budget']}]},before=structuredClone(p);
 const query=housingQueryProfile(p);assert.deepEqual(p,before);assert.deepEqual(query.criteria,[]);assert.deepEqual(query.questions,[]);assert.deepEqual(query.context.slice(0,2),p.context);assert.ok(query.context.some(c=>c.key==='housing_reference'&&c.value==='requested'));assert.ok(p.criteria[0].hard);assert.equal(p.questions.length,1);
});
test('saturated distance utility does not invent an advantage for a shorter distance',()=>{
 const p=profile(),r=run(p,{a:{mart:100,school:200},b:{mart:300,school:400}});const v=candidateViews(p,r,places);assert.equal(v[0].comparisons.length,0);assert.match(v[0].comparisonNote,/평가값 차이 없음/);
});
test('unknown peer cannot generate a comparison; a verified zero stays a measurement',()=>{
 const p=profile(),r=run(p,{a:{mart:0},b:{}}),v=candidateViews(p,r,places);assert.equal(v[0].comparisons.length,0);assert.equal(v[0].rows[0].known,true);assert.equal(v[0].rows[0].measure,'0m · 직선거리');assert.equal(v[0].unknown.length,1);assert.equal(v[1].unknown.length,2);
});
test('comparison uses personal curve and actual weight, not raw distance alone',()=>{
 const p=profile();p.criteria[1].utility={direction:'higher',ideal:5,limit:0,unit:'count'};const v=candidateViews(p,run(p,{a:{mart:800,school:1},b:{mart:1200,school:4}}),places);assert.equal(v[0].comparisons.length,2);assert.match(v[0].comparisons[0].text,/mart.*유리/);assert.match(v[0].comparisons[1].text,/school.*불리/);assert.equal(v[0].rows[0].contribution,42);
});
test('target preference favors the requested target over a smaller raw value',()=>{
 const p=profile();p.criteria[0].utility={direction:'target',ideal:100,limit:50,unit:'m2'};const v=candidateViews(p,run(p,{a:{mart:100},b:{mart:60}}),places);assert.match(v[0].comparisons[0].text,/유리/);
});
test('foreign evidence and inconsistent weights withhold comparison explanation',()=>{
 const p=profile(),r=run(p,{a:{mart:800},b:{mart:1200}});r.modules[0].evidence[0].candidate_id='b';r.report.assessments[1].details[0].weight=.7;const v=candidateViews(p,r,places);assert.equal(v[0].rows[0].known,false);assert.equal(v[0].rows[0].fact,null);assert.equal(v[1].rows[0].known,false);assert.equal(v[0].comparisons.length,0);
});
test('zero-weight housing unknown hard status remains visible beside a failed hard condition',()=>{
 const p=profile();p.groups.push({id:'housing',weight:0});p.criteria[0].hard={operator:'lte',value:700};p.criteria.push(criterion('budget','housing',{hard:{operator:'lte',value:400000000}}));const r=run(p,{a:{mart:800},b:{mart:600}});r.report.assessments[0].details[0].hard_status='fail';r.report.assessments[0].eligibility='ineligible';const v=candidateViews(p,r,places);assert.equal(v[0].hardFailed.length,1);assert.equal(v[0].hardUnknown[0].criterion.id,'budget');assert.equal(v[0].comparisons.length,0);
});
test('facility evidence is tied to candidate and condition; missing partial lists do not confirm counts',()=>{
 const p=profile(),r=run(p,{a:{},b:{}});r.education_details=[{candidate_id:'a',criterion_id:'school',selected:[{id:'schoolA',name:'시험 학교'}],note:'누락 있음'},{candidate_id:'b',criterion_id:'school',selected:[{id:'schoolB'}]}];r.leisure_details=[{candidate_id:'a',criterion_id:'mart',registered_leads:[{id:'gym'}]}];const v=candidateViews(p,r,places);assert.equal(v[0].rows[1].known,false);assert.equal(v[0].rows[1].facilities[0].id,'schoolA');assert.equal(v[0].rows[1].facilities.length,1);assert.equal(v[1].rows[1].facilities[0].id,'schoolB');assert.equal(v[0].rows[0].registeredLeads,true);
});
test('conflicting data and failed module have different unknown states',()=>{
 const p=profile(),r=run(p,{a:{},b:{}});r.modules[0].status='failed';r.modules[0].evidence[0].status='conflicting';const v=candidateViews(p,r,places);assert.equal(v[0].rows[0].reason,'자료 충돌');assert.equal(v[1].rows[0].reason,'조회 실패');
});
test('research status keeps related quote separate from not executed, failed and no quote',()=>{
 const v=researchCounts([{status:'completed',evidence_status:'found'},{status:'completed',evidence_status:'not_found'},{status:'completed',evidence_status:'unverified'},{status:'not_executed'},{status:'failed'},{status:'cancelled'},{status:'running'}]);assert.deepEqual(v,{related:1,no_quote:1,unknown:1,not_executed:1,failed:1,cancelled:1,pending:1});assert.equal(measure(null,'KRW'),'미확인');
});
