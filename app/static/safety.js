"use strict";
const safetyTopics = {night:'야간 보행 안전',traffic:'보행·교통사고',flood:'침수·재해',noise:'소음',air:'대기환경'};
function safetyContextText(fact) {
  if (['safety_reference','safety_research','safety_radius_m','safety_topics'].includes(fact.key)) return null;
  return educationContextText(fact);
}
function initSafety(data) {
  $('safety-data-note').textContent = data.available
    ? `CCTV 등록 ${data.registered_rows.toLocaleString()}행 · 서로 다른 좌표 ${data.coordinate_points.toLocaleString()}지점. 공개본 수정 ${data.publication_date}. 좌표 오류 분리 ${data.excluded_coordinate_rows ?? '미확인'}행. 작동 여부·실제 안전도는 미확인.`
    : 'CCTV 자료 또는 후보의 행정경계가 준비되지 않았어요. 문제별 니즈는 보존해요.';
}
function updateSafetyControls() {
  $('safety-fields').disabled = state.busy;
  $('safety-cancel').hidden = !reviewState.job || !(state.run?.safety_research_scope || []).length;
}
function renderSafetyProfile() {
  resetEdits('safety-form');
  state.safetyDirty = false;
  const p = state.profile;
  const context = key => p.context.find(c=>c.key===key)?.value;
  const selected = (context('safety_topics') || '').split(',');
  for (const input of document.querySelectorAll('[name="safety-topic"]')) input.checked = selected.includes(input.value);
  $('safety-weight').value = p.groups.find(g=>g.id==='safety')?.weight ?? 30;
  $('safety-importance').value = p.criteria.find(c=>c.module_id==='safety' && c.importance>0)?.importance ?? 100;
  $('safety-radius').value = context('safety_radius_m') || 500;
  $('safety-research').checked = context('safety_research') === 'requested';
}
function resetSafety() { $('safety-panel').hidden=true; $('safety-status').textContent=''; }
function setSafetyStatus(text) {
  if ((state.run?.safety_research_scope || []).length) $('safety-status').textContent=text;
}
function renderSafety() {
  const ref = state.run?.references?.find(r=>r.module_id==='safety');
  if (!ref) return resetSafety();
  $('safety-panel').hidden=false; $('safety-reference').replaceChildren(); $('safety-research-result').replaceChildren();
  $('safety-reference').append(node('p',`직선반경 ${ref.radius_m}m · CCTV 등록 좌표 참고`),
    reviewLink('진주시 CCTV 공개 원본',ref.source_url),node('p',`공개본 수정일 ${ref.publication_date || '미확인'} · 원본 조회 ${ref.retrieved_at ? new Date(ref.retrieved_at).toLocaleString('ko-KR') : '미확인'}`,'hint'));
  for (const o of ref.observations) {
    const c=state.candidates.find(c=>c.id===o.candidate_id);
    const box=node('article',undefined,'fact'); box.append(node('strong',c?.label || o.candidate_id));
    if (['available','stale'].includes(o.status)) {
      box.append(node('p',`${o.area_name} · 반경 내 등록 ${o.registered_rows_within_radius}행 / 좌표 ${o.registered_coordinate_points_within_radius}지점 · 최근접 ${Math.round(o.nearest_distance_m)}m`));
      box.append(node('p',`등록 목적: ${o.purposes_within_radius.join(', ') || '반경 내 확인된 지점 없음'}`,'hint'));
      box.append(node('p',`최근접 원본 행: ${o.nearest_source_records.join(', ')}`,'hint'));
      if (o.status==='stale') box.append(node('p','공개본 수정일이 1년을 넘은 과거 등록 참고예요. 현재 상태는 미확인.','unknown'));
    } else box.append(node('p',o.status==='outside_scope'?'준비된 진주 읍면동 경계 밖이라 연결하지 않았어요.':'자료 또는 경계를 확인할 수 없어요.','unknown'));
    $('safety-reference').append(box);
  }
  const details=node('details'); details.append(node('summary','등록 자료의 해석과 누락'));
  for (const text of ref.limitations) details.append(node('p',text,'hint'));
  $('safety-reference').append(details);
  const research=reviewState.result?.safety;
  if (research) {
    for (const item of research.items) {
      const box=node('article',undefined,'fact'); box.append(node('strong',item.area_name));
      for (const e of item.excerpts) box.append(node('p',safetyTopics[e.topic]+' · 공식 발표'),node('blockquote',e.quote),
        node('p','AI 해석: '+e.interpretation),reviewLink(e.title,e.source_url),node('p',`작성 ${e.published_date}`,'hint'));
      if (item.unconfirmed_topics.length) box.append(node('p','확인할 근거를 찾지 못한 문제: '+item.unconfirmed_topics.map(k=>safetyTopics[k]).join(', '),'unknown'));
      $('safety-research-result').append(box);
    }
    $('safety-status').textContent=`지역 보완 조사 완료 · ${new Date(research.checked_at).toLocaleString('ko-KR')}. 찾지 못한 자료는 미확인이며, 안전·위험 판정이나 점수에 반영하지 않았어요.`;
  } else if (reviewState.result?.errors?.some(e=>e.module==='safety')) $('safety-status').textContent='지역 보완 조사를 완료하지 못했어요. 문제별 근거는 미확인으로 남겼어.';
  else if (state.run.safety_research_status) $('safety-status').textContent='조사할 문제나 공식 행정동 범위를 확인할 수 없어 보완을 실행하지 않았어요.';
  else if (state.run.research_status==='busy') $('safety-status').textContent='다른 AI 작업 때문에 보완을 시작하지 못했어요. 작업 종료 후 비교를 새로 실행해 주세요.';
  else if ((state.run.safety_research_scope || []).length) $('safety-status').textContent='최신 공식 지역자료를 조사하고 있어요.';
  else $('safety-status').textContent='추가 웹 조사를 요청하지 않았어요. 등록 정보만 참고해요.';
  const searched = new Set((state.run.safety_research_scope || []).map(t=>t.area_code));
  const remaining = [...new Set(ref.observations.filter(o=>o.area_code&&!searched.has(o.area_code)).map(o=>o.area_name))];
  if (searched.size) $('safety-research-result').append(node('p','조사 범위: '+state.run.safety_research_scope.map(t=>t.area_name).join(', ')+'. 진주시청 공개 게시글, 최대 3개 지역.'+(remaining.length?' 이번에 조사하지 않은 지역: '+remaining.join(', '):''),'hint'));
  updateSafetyControls();
}
watchEdits('safety-form',{'safety-topic':'topics','safety-weight':'group_weight','safety-importance':'criterion_importance','safety-radius':'radius_m','safety-research':'qualitative_research'});
$('safety-form').addEventListener('input',()=>{state.safetyDirty=true;updateCompare();notice('안전·환경 조건을 수정했어요. 조건 적용을 누르면 반영돼요.');});
$('safety-form').addEventListener('submit',async event=>{
  event.preventDefault(); if(state.busy)return;busy(true);
  try {
    const result=await api('/api/safety-profile',{profile:state.profile?withRules(withWeights(state.profile,false)):null,edited_fields:editedFields('safety-form'),
      topics:[...document.querySelectorAll('[name="safety-topic"]:checked')].map(i=>i.value),
      group_weight:Number($('safety-weight').value),criterion_importance:Number($('safety-importance').value),
      radius_m:Number($('safety-radius').value),qualitative_research:$('safety-research').checked});
    setProfile(result.profile);notice('안전·환경 니즈를 반영했어요. 중요도와 후보를 확인해 주세요.');
  }catch(error){notice(error.message,true);}finally{busy(false);}
});
$('safety-cancel').addEventListener('click',()=>{$('reviews-cancel').click();setSafetyStatus('보완 조사 취소를 요청했어요.');});
