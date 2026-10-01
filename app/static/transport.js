"use strict";
const stopMetric = 'bus_stop_straight_line_distance_m';
function currentStop() {
  return state.profile?.criteria.find(c => c.module_id === 'transport' && c.metric === stopMetric);
}
function updateTransportControls() {
  $('transport-fields').disabled = state.busy;
  $('stop-fields').disabled = state.busy || !$('include-stop').checked;
  $('stop-hard-limit').disabled = state.busy || !$('include-stop').checked || !$('stop-mandatory').checked;
}
function renderTransportProfile() {
  resetEdits('transport-form');
  state.transportDirty = false;
  const p = state.profile, stop = currentStop();
  const context = key => p.context.find(c => c.key === key)?.value || '';
  const mode = context('travel_mode');
  $('travel-mode').value = /여러|혼합/.test(mode) ? 'mixed' : /자차|자동차|car/.test(mode) ? 'car'
    : /버스|bus/.test(mode) ? 'bus' : /도보|walking/.test(mode) ? 'walking' : 'unknown';
  $('travel-destination').value = context('travel_destination');
  $('travel-time').value = context('travel_time');
  $('include-stop').checked = !!stop && (stop.importance > 0 || !!stop.hard);
  $('stop-ideal').value = stop?.utility?.ideal ?? 300;
  $('stop-limit').value = stop?.utility?.limit ?? 1000;
  $('transport-weight').value = p.groups.find(g => g.id === (stop?.group_id || 'transport'))?.weight ?? 30;
  $('stop-importance').value = stop?.importance ?? 100;
  $('stop-mandatory').checked = !!stop?.hard;
  $('stop-hard-limit').value = stop?.hard?.value ?? stop?.utility?.limit ?? 1000;
  updateTransportControls();
}
$('include-stop').addEventListener('change', updateTransportControls);
$('stop-mandatory').addEventListener('change', updateTransportControls);
watchEdits('transport-form',{'travel-mode':'mode','travel-destination':'destination','travel-time':'time_of_day','include-stop':'include_stop','stop-ideal':'ideal','stop-limit':'limit','transport-weight':'group_weight','stop-importance':'importance','stop-mandatory':'mandatory_limit','stop-hard-limit':'hard_limit'});
$('transport-form').addEventListener('input', () => {
  state.transportDirty = true;
  notice('교통 조건을 수정했어. 교통 조건 적용을 누르면 비교에 반영돼.');
  updateCompare();
});
function appendCategoryContributions(card, assessment) {
  const box = node('div', undefined, 'category-contributions');
  for (const group of state.profile.groups) {
    const ids = state.profile.criteria.filter(c => c.group_id === group.id).map(c => c.id);
    const details = assessment.details.filter(d => ids.includes(d.criterion_id));
    const weight = details.reduce((s, d) => s + d.weight, 0);
    if (!weight) continue;
    const known = details.reduce((s, d) => s + (d.status === 'known' ? d.weight : 0), 0);
    const contribution = details.reduce((s, d) => s + (d.contribution ?? 0), 0);
    box.append(node('p', `${group.label} · 비중 ${(weight*100).toFixed(1)}% · 확인된 기여 ${contribution.toFixed(1)}점`
      + (weight-known > 1e-9 ? ` · 미확인 비중 ${((weight-known)*100).toFixed(1)}%` : '')));
  }
  card.append(box);
}
$('transport-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (state.busy || !state.profile) return;
  // Preserve pending distance/weight edits without confirming untouched AI proposals.
  let profile;
  try { profile = withRules(withWeights(state.profile, false)); }
  catch(error) { return notice(error.message, true); }
  busy(true);
  try {
    const result = await api('/api/transport-profile', {
      profile, mode:$('travel-mode').value, destination:$('travel-destination').value.trim(),
      time_of_day:$('travel-time').value.trim(), include_stop:$('include-stop').checked,
      ideal:Number($('stop-ideal').value), limit:Number($('stop-limit').value),
      group_weight:Number($('transport-weight').value), importance:Number($('stop-importance').value),
      mandatory_limit:$('stop-mandatory').checked,
      hard_limit:$('stop-mandatory').checked?Number($('stop-hard-limit').value):null,
      edited_fields:editedFields('transport-form'),
    });
    setProfile(result.profile);
    notice('교통 조건을 반영했어. 같은 후보로 다시 비교하면 새 조건을 적용해.');
  } catch(error) { notice(error.message, true); }
  finally { busy(false); }
});
