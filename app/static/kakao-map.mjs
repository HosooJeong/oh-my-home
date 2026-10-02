// One SDK request per page. Failed attempts release their state so retry works.
export function createKakaoLoader({root=globalThis,document=root.document,fetch=root.fetch.bind(root),timeoutMs=15000}={}){
 let pending=null;
 const ready=()=>root.kakao?.maps?.Map&&root.kakao.maps.services?.Geocoder;
 const timed=(stage,start)=>new Promise((resolve,reject)=>{
  let cleanup=()=>{};const timer=setTimeout(()=>{cleanup();reject(Object.assign(new Error('map_load_timeout'),{stage}));},timeoutMs);
  const finish=(error)=>{clearTimeout(timer);if(error){cleanup();reject(Object.assign(new Error('map_load_failed'),{stage}));}else resolve();};
  try{cleanup=start(finish)||cleanup;}catch{finish(true);}
 });
 return function load(){
  if(ready())return Promise.resolve(root.kakao.maps);
  if(pending)return pending;
  pending=(async()=>{
   if(!root.kakao?.maps?.load){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);let key;
    try{const response=await fetch('/api/config',{signal:controller.signal});if(!response.ok)throw new Error();key=(await response.json()).javascriptKey;if(!key)throw new Error();}
    catch{throw Object.assign(new Error('map_config_failed'),{stage:'config'});}finally{clearTimeout(timer);}
    await timed('sdk-script',done=>{const script=document.createElement('script');script.src=`https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false&libraries=services`;script.onload=()=>done();script.onerror=()=>done(true);document.head.append(script);return()=>{script.onload=null;script.onerror=null;script.remove();};});
   }
   await timed('sdk-load',done=>root.kakao.maps.load(()=>done()));
   if(!ready())throw Object.assign(new Error('map_sdk_incomplete'),{stage:'sdk-load'});
   return root.kakao.maps;
  })().finally(()=>{pending=null;});
  return pending;
 };
}
export const loadKakaoMaps=createKakaoLoader();
