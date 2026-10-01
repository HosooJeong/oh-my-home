import test from 'node:test';
import assert from 'node:assert/strict';
import {selectedStates,eventStates,resultStates} from '../app/static/village-journey.mjs';
test('unselected categories are not invented as completed work',()=>{
 assert.deepEqual(selectedStates(['living']),{living:'waiting'});
 assert.equal(resultStates(['living'],{modules:[]}).living,'not_executed');
});
test('actual module boundaries drive waiting running and completed',()=>{
 const events=[{stage:'module_started',module_id:'living'}];
 assert.deepEqual(eventStates(['living','education'],events),{living:'running',education:'waiting'});
 events.push({stage:'module_finished',module_id:'living',status:'completed'});
 assert.equal(eventStates(['living'],events).living,'completed');
});
test('a successful reference does not erase an incomplete scored module',()=>{
 assert.equal(eventStates(['safety'],[{stage:'module_finished',module_id:'safety',status:'partial'},{stage:'reference_started',module_id:'safety'},{stage:'reference_finished',module_id:'safety',status:'available'}]).safety,'partial');
});
test('unverified assessment and unexecuted research do not become complete',()=>{
 const run={modules:[{module_id:'leisure',status:'completed'}],profile:{criteria:[{id:'park',module_id:'leisure'}]},report:{assessments:[{details:[{criterion_id:'park',status:'unknown'}]}]}};
 assert.equal(resultStates(['leisure'],run).leisure,'partial');
 run.report.assessments=[];
 assert.equal(resultStates(['leisure'],run,[{module:'leisure',status:'not_executed'}]).leisure,'partial');
});
test('research stays running until its actual terminal status',()=>{
 const run={modules:[{module_id:'living',status:'completed'}]};
 assert.equal(resultStates(['living'],run,[{module:'living',status:'running'}]).living,'running');
 assert.equal(resultStates(['living'],run,[{module:'living',status:'completed',evidence_status:'found'}]).living,'completed');
 assert.equal(resultStates(['living'],run,[{module:'living',status:'completed',evidence_status:'not_found'}]).living,'partial');
 assert.equal(resultStates(['living'],run,[{module:'living',status:'cancelled'}]).living,'cancelled');
});
