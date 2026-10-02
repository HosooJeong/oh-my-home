"use strict";
let housingAvailable = false, housingBusy = false, housingTouched = false;
function updateHousingControls() {
  $('housing-fields').disabled = state.busy || housingBusy || !housingAvailable;
  $('housing-contract').disabled = $('housing-tenure').value === 'sale';
}
function housingFormat(value, unit) {
  if (value === null) return '요약 유보';
  const n = unit === 'm2' ? value : value / 10000;
  return n.toLocaleString('ko-KR', {maximumFractionDigits: unit === 'm2' ? 2 : 1}) +
    ({m2:'㎡', KRW:'만원', 'KRW/month':'만원/월', 'KRW/m2':'만원/㎡'}[unit] || ` ${unit}`);
}
function renderHousingReference(reference) {
  const target = $('housing-reference'); target.replaceChildren();
  target.append(node('p', reference.scope), node('p', `신고 거래 ${reference.sample_count.toLocaleString()}건 · 가격 점수 반영 0`, 'hint'));
  if (reference.status !== 'available') {
    target.append(node('p', {unavailable:'실거래 자료를 준비하지 못했어요. 자료 준비 후 서버를 다시 시작해 주세요.',
      empty:'이 범위의 거래 자료가 없어요. 0원이라는 뜻은 아니에요.',
      insufficient:'표본이 5건 미만이라 가격 요약을 유보했어요.'}[reference.status], 'unknown'));
    return;
  }
  const table = node('table'); const head = node('thead'), header = node('tr');
  for (const text of ['항목', '중앙값', '가운데 50% 범위', '전체 범위']) header.append(node('th', text));
  head.append(header); table.append(head);
  const body = node('tbody');
  for (const d of reference.distributions) {
    const row = node('tr'); row.append(node('th', d.label), node('td', housingFormat(d.median, d.unit)),
      node('td', `${housingFormat(d.q25, d.unit)} ~ ${housingFormat(d.q75, d.unit)}`),
      node('td', `${housingFormat(d.minimum, d.unit)} ~ ${housingFormat(d.maximum, d.unit)}`)); body.append(row);
  }
  table.append(body); const scroll = node('div'); scroll.style.overflowX='auto'; scroll.append(table); target.append(scroll);
  if ($('housing-tenure').value !== 'sale') {
    const c = reference.contract_counts;
    target.append(node('p', `신규 ${c.new}건 · 갱신 ${c.renewal}건 · 구분 미확인 ${c.unknown}건`, 'hint'));
  }
  target.append(node('p', '가운데 50%는 25~75백분위 구간이에요. 범위 안에 같은 가격의 집이 지금 있다는 뜻은 아니에요.', 'hint'));
}
async function queryHousing() {
  if (housingBusy || !housingAvailable) return;
  const query = {tenure:$('housing-tenure').value, legal_area:$('housing-area').value,
    area_min_m2:Number($('housing-area-min').value), area_max_m2:Number($('housing-area-max').value),
    contract:$('housing-tenure').value === 'sale' ? 'all' : $('housing-contract').value};
  if (query.area_min_m2 >= query.area_max_m2) {
    $('housing-reference').replaceChildren(node('p', '최대 면적은 최소 면적보다 크게 입력해 주세요.', 'unknown')); return;
  }
  housingBusy = true; updateHousingControls();
  try {renderHousingReference(await api('/api/housing-reference', query));$('housing-filter-status').textContent='';}
  catch(error) {$('housing-reference').replaceChildren(node('p', error.message, 'unknown'));}
  finally {housingBusy=false;updateHousingControls();}
}
async function initHousing(metadata) {
  housingAvailable = Boolean(metadata?.available);
  $('housing-data-note').textContent = housingAvailable
    ? `아파트 계약 ${metadata.period_start} ~ ${metadata.period_end} · 원본 조회 ${metadata.retrieved_at.slice(0,10)}. 매매 ${metadata.counts.sale.toLocaleString()}건, 전세 ${metadata.counts.jeonse.toLocaleString()}건, 월세 ${metadata.counts.monthly.toLocaleString()}건. 해제 매매 ${metadata.excluded.cancelled_sale}건 제외.`
    : '아파트 실거래 참고 자료가 아직 없어요. 생활·교통 비교는 계속 사용할 수 있어요.';
  for (const area of metadata?.legal_areas || []) {const option=node('option',area);option.value=area;$('housing-area').append(option);}
  for (const text of metadata?.limitations || []) $('housing-limitations').append(node('p',text,'hint'));
  updateHousingControls();
  if (housingAvailable) await queryHousing();
}
function renderHousingRun() {
  const reference=state.run?.references?.find(r=>r.module_id==='housing');
  if (!housingTouched && reference) {
    const tenure=state.profile.context.find(f=>f.key==='housing_tenure')?.value;
    $('housing-tenure').value=['sale','jeonse','monthly'].includes(tenure)?tenure:'sale';
    renderHousingReference(reference); updateHousingControls();
  }
}
$('housing-form').addEventListener('submit', event=>{event.preventDefault();if(!state.busy){housingTouched=true;queryHousing();}});
$('housing-form').addEventListener('input',()=>{housingTouched=true;$('housing-filter-status').textContent='조회 조건 수정 중 · 버튼을 눌러 반영해 주세요.';updateHousingControls();});
