"use strict";
state.candidateGeneration = null;
state.candidateMetadata = null;
function updateCandidateControls() {
  $('generation-fields').disabled = state.busy;
  $('generate-candidates').disabled = state.busy || !state.profile || state.transportDirty || state.educationDirty || state.safetyDirty || state.leisureDirty || !state.candidateMetadata?.available;
}
function initCandidateGeneration(metadata) {
  state.candidateMetadata = metadata;
  const select = $('generation-area');
  for (const area of metadata.areas || []) {
    const option = node('option', `${area.name} · ${area.point_count}지점`);
    option.value = area.code; select.append(option);
  }
  $('generation-data-note').textContent = metadata.available
    ? `진주 ${metadata.areas.length}개 읍면동 경계(${metadata.data_date}) 안의 ${metadata.point_count}개 분석 지점을 비교해. ${metadata.limitations}`
    : '경계·분석 자료가 준비되지 않아 자동 찾기를 사용할 수 없어요. 지도나 좌표로 후보를 선택해 주세요.';
  updateCandidateControls();
}
function clearCandidateGeneration() {
  state.candidateGeneration = null;
  $('generation-summary').textContent = '';
}
$('generation-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (state.busy || !state.profile || state.transportDirty || state.educationDirty || state.safetyDirty || state.leisureDirty) return;
  busy(true); notice('선택한 범위의 분석 지점을 같은 생활·교통 조건으로 비교하고 있어요.');
  try {
    const profile = withRules(withWeights(state.profile));
    const area = $('generation-area').value;
    const result = await api('/api/candidates', {profile, count:Number($('generation-count').value),
      separation_m:Number($('generation-separation').value), area_codes:area ? [area] : []});
    if (!['completed', 'limited'].includes(result.status)) {
      $('generation-summary').textContent = result.reason + (result.searched_count !== undefined
        ? ` 조회 ${result.searched_count} · 필수조건 탈락 ${result.hard_failed_count || 0} · 근거 미확인 ${result.unverified_count || 0}.` : '');
      notice(result.reason, true); return;
    }
    state.candidates = structuredClone(result.candidates);
    state.candidateGeneration = result;
    state.profile = profile;
    invalidate(); renderProfile(); renderCandidates(); drawMap(true);
    $('generation-summary').textContent = `선별 당시: ${result.searched_count}지점 조회 → 근거·필수조건 통과 ${result.eligible_count} → ${result.candidates.length}곳 선택. 필수조건 탈락 ${result.hard_failed_count}, 근거 미확인 제외 ${result.unverified_count}. 후보 간격 ${result.separation_m}m 이상. ${result.candidates.length < result.requested_count ? '요청한 수보다 적어. 지역·간격·필수조건을 확인해 주세요. ' : ''}이 목록을 비교하거나 지도에서 수정할 수 있어요.`;
    notice('분석 지점을 찾았어. 목록을 확인하고 내 기준으로 비교해 보세요.');
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
});
