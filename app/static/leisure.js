"use strict";
const leisureActivities={gym:'헬스',pilates:'필라테스',table_tennis:'탁구',swimming:'수영',tennis:'테니스',yoga:'요가',other:'직접 입력 취미'};
function updateLeisureControls(){
  $('leisure-fields').disabled=state.busy;
  $('leisure-cancel').hidden=!reviewState.job||!state.run?.leisure_research_scope;
}
function initLeisure(data){
  $('leisure-data-note').textContent=`등록 공원 ${data.counts.park}곳 · 도서관 ${data.counts.library}곳. 1년이 지났거나 미래인 공원 ${data.stale_or_future.park}곳 · 도서관 ${data.stale_or_future.library}곳. 오래된 자료가 있으면 최단거리 점수를 유보해. 사설 시설은 상가 목록과 웹검색으로 보완해.`;
}
function renderLeisureProfile(){
  resetEdits('leisure-form');
  state.leisureDirty=false;
  const p=state.profile;
  const find=m=>p.criteria.find(c=>c.module_id==='leisure'&&c.metric===m);
  const park=find('park_straight_line_distance_m'), library=find('library_straight_line_distance_m'), meeting=find('meeting_straight_line_distance_m'), hobby=find('hobby_suitability');
  $('include-park').checked=!!park&&park.importance>0;
  $('include-library').checked=!!library&&library.importance>0;
  $('include-meeting').checked=!!meeting&&meeting.importance>0;
  $('include-hobby').checked=!!hobby&&hobby.importance>0;
  $('park-type').value=park?.parameters.park_type||'any';
  $('library-type').value=library?.parameters.library_type||'any';
  $('leisure-ideal').value=(park||library||meeting)?.utility?.ideal??500;
  $('leisure-limit').value=(park||library||meeting)?.utility?.limit??1500;
  for(const [id,c,defaultValue] of [['park-importance',park,40],['library-importance',library,20],['meeting-importance',meeting,20],['hobby-importance',hobby,20]])$(id).value=c?.importance??defaultValue;
  $('meeting-label').value=meeting?.parameters.meeting_label||'';
  $('meeting-lat').value=meeting?.parameters.meeting_latitude||'';
  $('meeting-lon').value=meeting?.parameters.meeting_longitude||'';
  $('hobby-activity').value=hobby?.parameters.activity||'gym';
  $('hobby-form').value=hobby?.parameters.activity_form||'';
  $('hobby-name').value=hobby?.parameters.activity_name||'';
  $('leisure-weight').value=p.groups.find(g=>g.id==='leisure')?.weight??30;
}
function resetLeisure(){$('leisure-panel').hidden=true;$('leisure-status').textContent='';}
function appendLeisureDetails(card,candidateId){
  for(const detail of state.run.leisure_details||[]){
    if(detail.candidate_id!==candidateId)continue;
    const box=node('details');box.append(node('summary',detail.activity?'취미 시설 후보 · 점수 제외':'여가 시설과 확인 범위'));
    if(detail.activity){
      box.append(node('p',`${detail.activity_name||leisureActivities[detail.activity]||detail.activity} · ${detail.activity_form||'이용 형태 미지정'}. 등록 업종 후보이며 실제 형태는 웹 보완에서 확인해.`,'hint'));
      for(const r of detail.registered_leads)box.append(node('strong',r.name),node('p',`${r.address} · ${Math.round(r.distance_m)}m 직선거리`),node('p',`등록 업종 ${r.detail} · 자료 기준 ${r.date}`,'hint'));
      if(!detail.registered_leads.length)box.append(node('p','등록 목록에서 후보를 찾지 못했어. 시설이 없다는 뜻은 아니야.','unknown'));
    }else{
      box.append(node('p',detail.note));
      for(const r of detail.selected){
        box.append(node('strong',r.name),node('p',`${r.type} · ${r.address} · 자료 기준 ${r.date}`));
        const facilities=Object.values(r.facilities||{}).filter(Boolean).join(' / ');
        if(facilities)box.append(node('p','등록 시설 구성: '+facilities));
      }
    }
    card.append(box);
  }
}
function renderLeisure(){
  if(!state.run?.report)return resetLeisure();
  const active=state.profile.criteria.some(c=>c.module_id==='leisure'&&c.importance>0);
  $('leisure-panel').hidden=!active;
  $('leisure-research-result').replaceChildren();
  if(!active)return;
  const result=reviewState.result?.leisure;
  if(result){
    for(const item of result.discoveries){
      const card=node('article',undefined,'review-card');
      card.append(node('h3',item.name),node('p',item.address),node('p',`${leisureActivities[item.activity]} · ${item.role_label}`,'hint'),reviewLink('시설 원문 보기',item.source_url),node('p',item.note,'hint'));
      if(item.registered_id)card.append(node('p','공공 상가 목록의 같은 상호·도로명주소와 연결했어. 이용 형태와 점수는 별도야.','hint'));
      for(const e of item.excerpts)card.append(node('blockquote',e.quote),node('p','AI 해석: '+e.interpretation),node('p','작성 '+e.published_date,'hint'));
      $('leisure-research-result').append(card);
    }
    $('leisure-status').textContent=result.discoveries.length?`출처를 대조한 발견 후보 ${result.discoveries.length}곳. 전체 시설 수가 아니며 점수·필수조건에는 반영하지 않았어.`:'이번 웹검색에서 원문·지점·종목을 확인한 보완 자료를 찾지 못했어. 등록 후보를 참고하고 이용 형태는 미확인으로 남겨.';
  }else if(reviewState.cancelled)$('leisure-status').textContent='취미 보완 조사를 취소했어. 등록 후보와 미확인 조건을 유지했어.';
  else if(reviewState.result?.errors?.some(e=>e.module==='leisure')||reviewState.requested&&!reviewState.job)$('leisure-status').textContent='취미 웹 조사를 완료하지 못했어. 등록 후보와 미확인 조건을 유지했어.';
  else $('leisure-status').textContent=state.run.leisure_research_scope?'요청한 종목의 사설 시설 후보와 이용 형태를 웹으로 조사해.':'사설 취미를 선택하면 후보 발굴과 웹 보완이 이어져. 이용 조건이 미확인이면 전체 순위는 보류해.';
  updateLeisureControls();
}
watchEdits('leisure-form',{'include-park':'include_park','park-type':'park_type','include-library':'include_library','library-type':'library_type','leisure-ideal':'ideal','leisure-limit':'limit','park-importance':'park_importance','library-importance':'library_importance','include-meeting':'include_meeting','meeting-label':'meeting_label','meeting-lat':'meeting_latitude','meeting-lon':'meeting_longitude','meeting-importance':'meeting_importance','include-hobby':'include_hobby','hobby-activity':'activity','hobby-name':'activity_name','hobby-form':'activity_form','hobby-importance':'hobby_importance','leisure-weight':'group_weight'});
$('leisure-form').addEventListener('input',()=>{state.leisureDirty=true;updateCompare();notice('여가 조건을 수정했어. 조건 적용을 누르면 반영돼.');});
$('leisure-form').addEventListener('submit',async event=>{
  event.preventDefault();if(state.busy)return;
  let profile=null;
  try{if(state.profile)profile=withRules(withWeights(state.profile,false));}catch(error){return notice(error.message,true);}
  busy(true);
  try{
    const result=await api('/api/leisure-profile',{profile,edited_fields:editedFields('leisure-form'),include_park:$('include-park').checked,park_type:$('park-type').value,
      include_library:$('include-library').checked,library_type:$('library-type').value,ideal:Number($('leisure-ideal').value),limit:Number($('leisure-limit').value),
      park_importance:Number($('park-importance').value),library_importance:Number($('library-importance').value),
      include_meeting:$('include-meeting').checked,meeting_label:$('meeting-label').value.trim(),
      meeting_latitude:$('meeting-lat').value===''?null:Number($('meeting-lat').value),meeting_longitude:$('meeting-lon').value===''?null:Number($('meeting-lon').value),meeting_importance:Number($('meeting-importance').value),
      include_hobby:$('include-hobby').checked,activity:$('hobby-activity').value,activity_name:$('hobby-name').value.trim(),activity_form:$('hobby-form').value.trim(),hobby_importance:Number($('hobby-importance').value),group_weight:Number($('leisure-weight').value)});
    setProfile(result.profile);notice('여가 조건을 반영했어. 사설 취미를 선택했으면 비교 뒤 웹 보완이 이어져.');
  }catch(error){notice(error.message,true);}finally{busy(false);}
});
$('leisure-cancel').addEventListener('click',()=>{$('reviews-cancel').click();$('leisure-status').textContent='취미 보완 조사 취소를 요청했어.';});
