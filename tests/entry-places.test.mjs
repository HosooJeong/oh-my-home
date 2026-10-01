import test from 'node:test';
import assert from 'node:assert/strict';
import {entryReady,addCandidate,readCandidates} from '../app/static/entry-places.mjs';
import {emptyDraft,readDraft,buildRequest,toggleCategory} from '../app/static/village-model.mjs';
const p=(n=1)=>({id:'home_'+n,label:'검증용 주소 '+n,latitude:35.18+n*.001,longitude:128.1,origin:'user'});
test('known entries cannot proceed before one or multiple houses are confirmed',()=>{
 const d=emptyDraft();d.entry='single';assert.equal(entryReady(d),false);addCandidate(d,p());assert.equal(entryReady(d),true);
 d.entry='multiple';assert.equal(entryReady(d),false);addCandidate(d,p(2));assert.equal(entryReady(d),true);
 d.entry='discover';d.candidates=[];assert.equal(entryReady(d),true);
});
test('single selection replaces, multiple duplicates and over-six are rejected',()=>{
 const d=emptyDraft();d.entry='single';addCandidate(d,p());addCandidate(d,p(2));assert.equal(d.candidates.length,1);assert.equal(d.candidates[0].id,'home_2');
 d.entry='multiple';assert.throws(()=>addCandidate(d,{...p(2),id:'home_alias'}),/이미/);
 for(const n of [1,3,4,5,6])addCandidate(d,p(n));assert.throws(()=>addCandidate(d,p(7)),/6곳/);
});
test('candidate draft persists without putting precise home address into model prompt',()=>{
 const d=emptyDraft();d.entry='single';addCandidate(d,p());toggleCategory(d,'living');d.answers.living='마트가 가까우면 좋아.';
 const restored=readDraft(JSON.stringify(d));assert.deepEqual(restored.candidates,d.candidates);assert.equal(entryReady(restored),true);assert.ok(!buildRequest(restored).includes(d.candidates[0].label));
});
test('legacy drafts and invalid coordinates do not bypass the entry gate',()=>{
 const d=readDraft(JSON.stringify({version:1,entry:'single',blocks:[],location:'메모만 있음'}));assert.equal(entryReady(d),false);
 assert.deepEqual(readCandidates([{...p(),latitude:NaN},{...p(2),id:'../bad'},{...p(3),longitude:181}]),[]);
});
