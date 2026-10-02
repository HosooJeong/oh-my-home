"use strict";
function educationContextText(fact) {
  if (['education_research','qualitative_research_requested'].includes(fact.key)) return null;
  const levels = {elementary:'초등학교',middle:'중학교',high:'고등학교'};
  const subjects = {math:'수학',english:'영어',korean:'국어',science:'과학',art:'미술',music:'음악'};
  const modes = {unknown:'통학 방식 미정',alone:'혼자 도보',accompanied:'보호자 동행',car:'보호자 차량',shuttle:'셔틀'};
  return (fact.key === 'education_level' ? levels[fact.value] : fact.key === 'education_subject' ? subjects[fact.value]
    : fact.key === 'school_travel_mode' ? modes[fact.value] : null) || fact.value;
}
function updateEducationControls() { $('education-fields').disabled = state.busy; }
function initEducation(data) {
  $('education-data-note').textContent = data.available
    ? `진주 학교 ${data.counts.school}곳 · 학원 ${data.counts.academy}개소. 학원 위치 미연결 ${data.academy_unlocated}개소, 연계일이 오래됐거나 미래인 자료 ${data.academy_old_or_future}개소. 위치·학령·자료 시점이 빠진 경우 전체 개소와 점수는 미확인이에요.`
    : '교육 자료가 준비되지 않았어요. 조건은 보존하고 결과는 미확인으로 남겨.';
}
function renderEducationProfile() {
  resetEdits('education-form');
  state.educationDirty = false;
  const p = state.profile;
  const school = p.criteria.find(c => c.module_id === 'education' && c.metric === 'school_straight_line_distance_m');
  const academy = p.criteria.find(c => c.module_id === 'education' && c.metric === 'academy_count_within_radius');
  $('include-school').checked = !!school && (school.importance > 0 || !!school.hard);
  $('include-academy').checked = !!academy && (academy.importance > 0 || !!academy.hard);
  $('school-level').value = school?.parameters.school_level || academy?.parameters.school_level || 'elementary';
  $('school-ideal').value = school?.utility?.ideal ?? 500;
  $('school-limit').value = school?.utility?.limit ?? 1500;
  $('school-importance').value = school?.importance ?? 70;
  $('academy-subject').value = academy?.parameters.subject || 'math';
  $('academy-radius').value = academy?.parameters.radius_m || '1000';
  $('academy-sufficient').value = academy?.utility?.ideal ?? 3;
  $('academy-importance').value = academy?.importance ?? 30;
  $('education-weight').value = p.groups.find(g => g.id === 'education')?.weight ?? 30;
  const travel = p.context.find(c => c.key === 'school_travel_mode')?.value;
  $('school-travel').value = ['alone','accompanied','car','shuttle'].includes(travel) ? travel : 'unknown';
  $('education-research').checked = p.context.some(c => c.key === 'education_research' && c.value === 'requested');
}
watchEdits('education-form',{'school-level':'school_level','school-travel':'travel_mode','include-school':'include_school','school-ideal':'school_ideal','school-limit':'school_limit','school-importance':'school_importance','include-academy':'include_academy','academy-subject':'subject','academy-radius':'radius_m','academy-sufficient':'sufficient_count','academy-importance':'academy_importance','education-weight':'group_weight','education-research':'qualitative_research'});
$('education-form').addEventListener('input', () => {state.educationDirty = true; updateCompare(); notice('교육 조건을 수정했어요. 교육 조건 적용을 누르면 반영돼요.');});
$('education-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy) return;
  let profile = null;
  try { if (state.profile) profile = withRules(withWeights(state.profile, false)); }
  catch(error) { return notice(error.message, true); }
  busy(true);
  try {
    const result = await api('/api/education-profile', {profile,edited_fields:editedFields('education-form'),
      school_level:$('school-level').value, travel_mode:$('school-travel').value,
      include_school:$('include-school').checked, school_ideal:Number($('school-ideal').value), school_limit:Number($('school-limit').value),
      school_importance:Number($('school-importance').value), include_academy:$('include-academy').checked,
      subject:$('academy-subject').value, radius_m:Number($('academy-radius').value), sufficient_count:Number($('academy-sufficient').value),
      academy_importance:Number($('academy-importance').value), group_weight:Number($('education-weight').value),
      qualitative_research:$('education-research').checked});
    setProfile(result.profile); notice('교육 조건을 반영했어요. 후보를 비교하면 필요한 웹 보완 조사도 이어서 실행돼요.');
  } catch(error) {notice(error.message,true);} finally {busy(false);}
});
function appendEducationDetails(card, candidateId) {
  for (const detail of state.run.education_details || []) {
    if (detail.candidate_id !== candidateId) continue;
    const box = node('details'); box.append(node('summary','교육 시설과 확인 범위'),node('p',detail.note));
    for (const facility of detail.selected) {
      box.append(node('strong',facility.name),node('p',facility.address));
      if (facility.kind === 'academy') box.append(node('p',`${facility.courses} · 등록정원 ${facility.capacity ?? '미확인'} · 일시수용 ${facility.simultaneous_capacity ?? '미확인'}명. 실제 반 크기는 미확인.`, 'hint'));
    }
    card.append(box);
  }
}
