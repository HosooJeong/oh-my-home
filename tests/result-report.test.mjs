import test from 'node:test';
import assert from 'node:assert/strict';
import {categoryReports,radarGeometry,researchNotes,criterionReason,overviewReasons,categoryScope} from '../app/static/result-report.mjs';
import {candidateViews,profileWeights} from '../app/static/analysis-view.mjs';
const criterion=(id,group,importance=1)=>({id,group_id:group,module_id:group,label:id,need:id,importance,utility:{direction:'lower',ideal:500,limit:1500,unit:'m'},hard:null});
const profile=()=>({groups:[{id:'living',label:'생활',weight:80},{id:'education',label:'교육',weight:20},{id:'housing',label:'비용',weight:0}],criteria:[criterion('mart','living'),criterion('clinic','living',3),criterion('school','education')],questions:[],context:[]});
test('official facility facts retain per-home scope while web discoveries disclose unknown distance',()=>{
 const requests=[{id:'edu',module:'education'},{id:'med',module:'health'}],fact={research_kind:'facility_fact',source_role:'operator',field:'department',value:'내과'};
 const data={items:[{facility_id:'known',candidate_ids:['a'],candidate_distances:{a:120},excerpts:[{...fact,request_ids:['med']}]},{facility_id:'new',web_discovery:true,excerpts:[{...fact,request_ids:['med']}]}]};
 const notes=researchNotes(data,requests,'health');assert.equal(notes.length,2);assert.deepEqual(notes[0].candidateIds,['a']);assert.equal(notes[0].candidateDistances.a,120);assert.equal(notes[0].role,'운영자의 공식 안내');assert.match(notes[1].scope,/집별 거리.*미확인/);assert.deepEqual(notes[1].candidateDistances,{});assert.equal(researchNotes(data,requests,'education').length,0);
});
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
 assert.equal(report[0].score,0);assert.deepEqual(g.point(0,report[0].score),[220,202]);assert.equal(report[3].status,'unselected');assert.equal(report.find(c=>c.id==='housing').status,'reference');assert.equal(report.find(c=>c.id==='housing').score,null);
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
 const p={groups:[{id:'housing',weight:0}],criteria:[{...criterion('budget','housing'),hard:{operator:'lte',value:4e8}}]},r=categoryReports(p,null,['housing']);const h=r.find(c=>c.id==='housing');assert.equal(h.score,null);assert.equal(h.hardUnknown.length,1);assert.equal(h.rows[0].reason,'집별 조건 미확인');
});
test('additional groups stay in the report while the hexagon keeps six fixed axes',()=>{
 const p=profile();p.groups.push({id:'extension',label:'추가 요소',weight:10});p.criteria.push(criterion('other','extension'));const [v]=views(p,{a:{mart:500,clinic:500,school:500,other:500}}),r=categoryReports(p,v,['extension']);assert.equal(r.length,8);assert.equal(r.find(c=>c.id==='extension').score,100);assert.equal(radarGeometry(r).axes.length,6);
});
test('qualitative notes require category-bound request IDs and remain distinct from candidate scores',()=>{
 const requests=[{id:'living_r',module:'living'},{id:'school_r',module:'education'},{id:'safety_r',module:'safety'},{id:'hobby_r',module:'leisure',criterion_ids:['hobby']}],data={items:[{facility_id:'mart',excerpts:[{quote:'생활',request_ids:['living_r']},{quote:'학원',request_ids:['school_r']},{quote:'연결 없음'}]}],safety:{items:[{area_name:'지역',excerpts:[{quote:'안전',request_ids:['safety_r']}]}]},leisure:{discoveries:[{name:'후보',criterion_id:'hobby',note:'날짜 미확인',excerpts:[]},{name:'취미',excerpts:[{quote:'경험',request_ids:['hobby_r']}]}]}};
 assert.deepEqual(researchNotes(data,requests,'living').map(n=>n.excerpt?.quote),['생활']);assert.deepEqual(researchNotes(data,requests,'education').map(n=>n.excerpt?.quote),['학원']);assert.equal(researchNotes(data,requests,'safety')[0].kind,'area');assert.equal(researchNotes(data,requests,'leisure').length,2);assert.equal(researchNotes(data,requests,'housing').length,0);assert.equal(researchNotes(data,requests).length,6);
});
test('evaluation reason uses the candidate measurement and personal target, while missing stays undecided',()=>{
 const p=profile(),[v]=views(p,{a:{mart:800,clinic:200,school:null}});assert.match(criterionReason(v.rows[0]),/목표보다 300m 더 멀어/);assert.match(criterionReason(v.rows[1]),/목표 수준을 충족/);assert.match(criterionReason(v.rows[2]),/충족 여부는 미확인/);
});

const distanceRow=(metric='convenience_straight_line_distance_m',overrides={})=>({known:true,fit:1,weight:.7,reason:'자료 미확인',criterion:{...criterion('convenience','living'),metric},fact:{value:220,unit:'m',source_record:'shop:a'},facilities:[{id:'shop:a',name:'씨유 시험점'}],...overrides});
test('named convenience explanation ties the observed straight-line distance to the preference, never walking or current operation',()=>{
 const row=distanceRow(),before=structuredClone(row),text=criterionReason(row);
 assert.match(text,/씨유 시험점.*직선거리 220m.*편의점이 가까운.*선호에 잘 맞/);
 assert.doesNotMatch(text,/도보 \d|차량|분 거리|영업 중|운영 중/);assert.deepEqual(row,before);
 assert.match(categoryScope({id:'living',rows:[row]}),/실제 이동 경로·시간은 미확인.*현재 영업 여부/);
});
test('flexible mart preference is described without inventing car ownership or replacing explicit numeric rules',()=>{
 const row=distanceRow('grocery_straight_line_distance_m');row.criterion.comparison_proposal={label:'조금 멀어도 괜찮아요',utility:{...row.criterion.utility},radius_m:null};
 assert.match(criterionReason(row),/마트는 조금 멀어도 괜찮다는 선호/);assert.doesNotMatch(criterionReason(row),/차량|자동차|운전|도보/);
 row.criterion.utility.ideal=600;assert.doesNotMatch(criterionReason(row),/조금 멀어도 괜찮다는/);
});
test('unrelated facility identity or missing facility cannot supply a name to a bound distance',()=>{
 const row=distanceRow();row.facilities=[{id:'shop:b',name:'다른 집 매장'}];
 assert.match(criterionReason(row),/등록자료로 확인한 편의점.*220m/);assert.doesNotMatch(criterionReason(row),/다른 집 매장/);
 row.facilities=[];assert.doesNotMatch(criterionReason(row),/undefined|null/);
});
test('partially satisfied and zero-fit distance explanations remain preferences without implying candidate exclusion',()=>{
 const row=distanceRow();row.fit=.6;assert.match(criterionReason(row),/조금 아쉬운/);row.fit=0;assert.match(criterionReason(row),/선호와 차이가 큰/);
 assert.doesNotMatch(criterionReason(row),/탈락|추천 제외|도보로.*힘들/);row.fact.value=0;row.fit=1;assert.match(criterionReason(row),/직선거리 0m/);
});
test('unknown or conflicting evidence never becomes a named satisfied facility, even with a partial value/list',()=>{
 const row=distanceRow();row.known=false;row.fit=null;assert.match(criterionReason(row),/미확인/);assert.doesNotMatch(criterionReason(row),/씨유 시험점|220m|잘 맞/);
 row.reason='자료 충돌';assert.match(criterionReason(row),/자료가 서로 맞지 않아/);row.reason='현재 정량 평가 미지원';assert.match(criterionReason(row),/평가하기 어려워/);
});
test('school and bus proximity do not imply school assignment, route safety, usable service or walking distance',()=>{
 for(const [metric,id,scope] of [['school_straight_line_distance_m','education',/배정 학교.*통학로 안전/],['bus_stop_straight_line_distance_m','transport',/노선·방향·배차/]]){
  const row=distanceRow(metric);assert.match(criterionReason(row),/직선거리/);assert.match(categoryScope({id,rows:[row]}),scope);
 }
 const row=distanceRow('meeting_straight_line_distance_m');row.fact.source_record='user:meeting';row.facilities=[];row.criterion.parameters={meeting_label:'함께 만날 장소'};assert.match(criterionReason(row),/지정하신 함께 만날 장소/);assert.doesNotMatch(criterionReason(row),/가장 가까운/);
});
test('verified academy count explains its subject, level, search scope and examples without claiming course quality',()=>{
 const row=distanceRow('academy_count_within_radius',{fact:{value:4,unit:'count',source_record:'education-snapshot'},facilities:[{id:'a',kind:'academy',name:'시험 수학학원'},{id:'b',kind:'academy',name:'다른 수학학원'}]});
 row.criterion.utility={direction:'higher',ideal:3,limit:0,unit:'count'};row.criterion.parameters={school_level:'elementary',subject:'math',radius_m:'1500'};
 const text=criterionReason(row);assert.match(text,/직선반경 1,500m.*초등학생 수학 학원 4곳.*시험 수학학원.*선호에 잘 맞/);
 assert.doesNotMatch(text,/수업이 좋|만족도가 높|모집 중/);assert.match(categoryScope({id:'education',rows:[row]}),/수업의 질·현재 모집 여부/);
 row.fact.value=1;row.fit=0;assert.doesNotMatch(criterionReason(row),/선택지가 없어|확인되지 않아/);
 row.fact.value=0;row.facilities=[];assert.match(criterionReason(row),/등록자료에서 원하는 학원이 확인되지 않아/);
});
test('partial academy inventory cannot be narrated as a complete total or confirmed satisfaction',()=>{
 const row=distanceRow('academy_count_within_radius',{known:false,fit:null,fact:{value:2,unit:'count'},facilities:[{id:'a',kind:'academy',name:'부분 학원'}]});
 assert.match(criterionReason(row),/미확인/);assert.doesNotMatch(criterionReason(row),/2곳|부분 학원|잘 맞/);
});
test('overview explains the selected candidate and highest-priority confirmed needs only, without changing scores or input',()=>{
 const rows=[distanceRow(),distanceRow('grocery_straight_line_distance_m',{weight:.3,fact:{value:82,unit:'m',source_record:'mart:a'},facilities:[{id:'mart:a',name:'시험 마트'}]}),distanceRow('park_straight_line_distance_m',{weight:0}),distanceRow('school_straight_line_distance_m',{known:false,fit:null,weight:.9})],view={rows},before=structuredClone(view);
 const reasons=overviewReasons(view);assert.equal(reasons.length,2);assert.match(reasons[0],/씨유 시험점/);assert.match(reasons[1],/시험 마트.*82m/);assert.deepEqual(view,before);
 rows[0].fact.source_record='shop:b';rows[0].facilities=[{id:'shop:b',name:'비교 집 편의점'}];assert.match(overviewReasons(view)[0],/비교 집 편의점/);assert.doesNotMatch(overviewReasons(view)[0],/씨유 시험점/);
});

test('six fully verified categories close every edge including the last-to-first edge; target and score remain independent',()=>{
 const ids=['living','transport','education','health','leisure','dining'],p={groups:ids.map((id,i)=>({id,label:id,weight:i===1?50:10})),criteria:ids.map(id=>criterion(id,id)),context:[],questions:[]};
 const values=Object.fromEntries(ids.map((id,i)=>[id,500+i*100]));const [v]=views(p,{a:values});const reports=categoryReports(p,v,ids),geo=radarGeometry(reports);
 assert.equal(geo.complete,true);assert.equal(geo.actual.length,6);assert.equal(geo.target.length,6);
 assert.deepEqual(geo.actual[5],[geo.point(5,reports[5].score),geo.point(0,reports[0].score)]);
 assert.deepEqual(reports.map(c=>c.target),[100,100,100,100,100,100]);
 values.health=null;const [partial]=views(p,{a:values});const open=radarGeometry(categoryReports(p,partial,ids));
 assert.equal(open.complete,false);assert.equal(open.axes[3].score,null);assert.equal(open.actual.length,4);
});
test('medical and dining explanations disclose registered access without medical quality, taste or current-operation claims',()=>{
 for(const [metric,id,limitation] of [['clinic_straight_line_distance_m','health',/진료 수준·응급 대응/],['everyday_meal_straight_line_distance_m','dining',/맛·가격·식단 적합성/]]){
  const row=distanceRow(metric);const text=criterionReason(row);assert.match(text,/직선거리 220m/);assert.doesNotMatch(text,/치료를 잘|맛있는|운영 중|도보/);assert.match(categoryScope({id,rows:[row]}),limitation);
  if(id==='health')assert.match(categoryScope({id,rows:[row]}),/거리 점수.*진료과 확인과는 별개/);
 }
});
