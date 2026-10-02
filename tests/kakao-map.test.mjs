import test from 'node:test';
import assert from 'node:assert/strict';
import {createKakaoLoader} from '../app/static/kakao-map.mjs';

const maps=()=>({Map:class{},services:{Geocoder:class{}},load:done=>done()});
function harness(){
 const root={};let fetches=0,appends=0,removed=0,failScript=false;
 const document={createElement:()=>({remove(){removed++;}}),head:{append(script){appends++;queueMicrotask(()=>{if(failScript)script.onerror();else{root.kakao={maps:maps()};script.onload();}});}}};
 const load=createKakaoLoader({root,document,fetch:async()=>{fetches++;return {ok:true,json:async()=>({javascriptKey:'public-test-key'})};},timeoutMs:30});
 return {root,load,setFail:v=>failScript=v,counts:()=>({fetches,appends,removed})};
}
test('already usable SDK is reused without requesting configuration or scripts',async()=>{
 const h=harness();h.root.kakao={maps:maps()};assert.equal(await h.load(),h.root.kakao.maps);assert.deepEqual(h.counts(),{fetches:0,appends:0,removed:0});
});
test('simultaneous map requests share a single SDK attempt',async()=>{
 const h=harness(),a=h.load(),b=h.load();assert.equal(a,b);assert.equal(await a,await b);assert.deepEqual(h.counts(),{fetches:1,appends:1,removed:0});
});
test('a failed configuration attempt does not poison the next retry',async()=>{
 const h=harness();let count=0;
 const load=createKakaoLoader({root:h.root,document:{createElement:()=>({remove(){}}),head:{append(s){h.root.kakao={maps:maps()};queueMicrotask(()=>s.onload());}}},fetch:async()=>({ok:++count>1,json:async()=>({javascriptKey:'public-test-key'})})});
 await assert.rejects(load(),e=>e.stage==='config');assert.equal(await load(),h.root.kakao.maps);assert.equal(count,2);
});
test('failed script is removed and retry can complete',async()=>{
 const h=harness();h.setFail(true);await assert.rejects(h.load(),e=>e.stage==='sdk-script');assert.equal(h.counts().removed,1);h.setFail(false);assert.equal(await h.load(),h.root.kakao.maps);assert.equal(h.counts().appends,2);
});
test('a stalled SDK callback times out and can be retried without duplicate script',async()=>{
 const root={kakao:{maps:{load(){}}}};let appends=0;
 const load=createKakaoLoader({root,document:{head:{append(){appends++;}}},fetch:async()=>{throw Error('unexpected fetch');},timeoutMs:10});
 await assert.rejects(load(),e=>e.stage==='sdk-load');root.kakao.maps.load=done=>{root.kakao.maps=maps();done();};assert.equal(await load(),root.kakao.maps);assert.equal(appends,0);
});
