"use strict";
const reviewState = {key:null, job:null, accepted:false, cancelled:false, requested:false, result:null, selected:new Set()};
const topics = {size:'규모', selection:'품목', price:'가격', service:'서비스', experience:'이용 경험',course:'과목·수업 형태',teaching:'수업 경험'};
const sentiments = {positive:'만족 의견', negative:'불만 의견', mixed:'만족·불만 혼합', neutral:'경험 설명'};
function reviewLink(label, url) {
  const link = node('a', label, 'external-link');
  link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
  return link;
}
function resetReviews() {
  reviewState.key = null; reviewState.requested = false; reviewState.result = null; reviewState.cancelled = false;
  reviewState.selected.clear(); $('reviews-panel').hidden = true;
}
function updateReviewControls() {
  $('reviews-search').disabled = state.busy || reviewState.requested || !reviewState.selected.size;
  for (const input of document.querySelectorAll('#review-facilities input')) input.disabled = state.busy || reviewState.requested;
}
function renderReviews() {
  if (!state.run?.report) return resetReviews();
  const facilities = Object.values(state.run.facilities).filter(f => ['shops','academy'].includes(f.kind));
  if (reviewState.key !== state.run.review_key) {
    resetReviews(); reviewState.key = state.run.review_key;
    facilities.filter(f => !state.run.research_facility_ids || state.run.research_facility_ids.includes(f.id)).slice(0, 3).forEach(f => reviewState.selected.add(f.id));
    $('reviews-status').textContent = '선택한 공공자료의 매장명·주소로 후기를 찾아요. 한 비교에서 1회, 최대 3곳을 조사할 수 있어요. 작성 2년 이내이고 원문·작성일·주소를 확인한 자료만 사용해요.';
  }
  $('reviews-panel').hidden = !facilities.length;
  $('review-facilities').replaceChildren();
  for (const facility of facilities) {
    const card = node('article', undefined, 'review-card');
    card.append(node('h3', facility.name), node('p', facility.address, 'hint'));
    const label = node('label', undefined, 'check');
    const input = node('input'); input.type = 'checkbox'; input.checked = reviewState.selected.has(facility.id);
    input.setAttribute('aria-label', `${facility.name} 후기 조사 선택`);
    input.addEventListener('change', () => {
      if (input.checked && reviewState.selected.size >= 3) {input.checked = false; $('reviews-status').textContent = '최대 3곳을 선택해 주세요.'; return;}
      if (input.checked) reviewState.selected.add(facility.id); else reviewState.selected.delete(facility.id);
      updateReviewControls();
    });
    label.append(input, document.createTextNode('후기 조사에 포함')); card.append(label);
    const links = node('div', undefined, 'review-links');
    links.append(reviewLink('카카오맵에서 보기', facility.review_links.kakao), reviewLink('네이버지도에서 보기', facility.review_links.naver));
    card.append(links);
    const result = reviewState.result?.items.find(i => i.facility_id === facility.id);
    if (result) {
      if (result.excerpts.length) card.append(node('p',
        `출처 ${new Set(result.excerpts.map(e => e.source_url)).size}개에서 문구 ${result.excerpts.length}개를 가져왔어요.`, 'hint'));
      for (const excerpt of result.excerpts) {
        const detail = node('div', undefined, 'review-excerpt');
        detail.append(node('strong', `${topics[excerpt.topic]} · ${sentiments[excerpt.sentiment]}`),
          node('blockquote', excerpt.quote), node('p', 'AI 요약: ' + excerpt.interpretation),
          reviewLink(excerpt.title, excerpt.source_url),
          node('p', excerpt.published_date ? `작성 ${excerpt.published_date}` : '작성일 미확인', 'hint'));
        const identity = node('details'); identity.append(node('summary', '같은 지점으로 연결한 근거'), node('p', excerpt.identity_note));
        detail.append(identity); card.append(detail);
      }
      if (!result.excerpts.length) card.append(node('p', result.status === 'unverified'
        ? '최신 작성일·원문·주소를 확인하지 못했거나 부정확한 근거여서 보완 내용을 보류했어요.' : '연결된 공개 웹에서 인용할 만한 후기를 찾지 못했어요.', 'unknown'));
      card.append(node('p', `조사 ${new Date(reviewState.result.checked_at).toLocaleString('ko-KR')}`, 'hint'));
    }
    $('review-facilities').append(card);
  }
  updateReviewControls();
}
async function startReviews(existingJob=null) {
  if (state.busy || reviewState.requested || !state.run || !existingJob && !reviewState.selected.size) return;
  const key = reviewState.key;
  const id = existingJob?.id || globalThis.crypto?.randomUUID?.() || `r${Date.now()}_${Math.random().toString(36).slice(2)}`;
  reviewState.job = id; reviewState.accepted = false; reviewState.cancelled = false;
  reviewState.requested = true; busy(true); $('reviews-cancel').hidden = false;
  $('reviews-status').textContent = '필요한 웹자료를 검색하고 원문·작성일·대상을 대조하고 있어요. 몇 분 걸릴 수 있어요.';
  if(typeof setSafetyStatus==='function')setSafetyStatus($('reviews-status').textContent);
  if(typeof updateSafetyControls==='function')updateSafetyControls();
  try {
    let job = existingJob || await api('/api/reviews', {request_id:id, run_id:state.run.run_id, facility_ids:[...reviewState.selected]});
    reviewState.accepted = true;
    if (reviewState.cancelled && job.status === 'running') await api('/api/jobs/' + id + '/cancel', {});
    while (job.status === 'running') {await new Promise(resolve=>setTimeout(resolve,900));job=await api('/api/jobs/'+id);}
    if (key !== reviewState.key) return;
    if (reviewState.cancelled || job.status === 'cancelled') $('reviews-status').textContent = '후기 조사를 취소했어요.';
    else if (job.status === 'completed') {
      reviewState.result = job.result; renderReviews();if(typeof renderLeisure==='function')renderLeisure();if(typeof renderSafety==='function')renderSafety();
      $('reviews-status').textContent = job.result.errors?.length ? '일부 웹 보완 조사를 완료하지 못했어요. 확인된 출처만 참고하고 나머지는 미확인으로 남겼어요.'
        : job.result.safety && !job.result.leisure && !job.result.items.length ? '이번에는 안전·환경의 공식 지역자료를 보완했어요. 상가 후기는 조사하지 않았어요.'
        : '최신 웹 보완 조사가 끝났어요. 일부 작성자의 경험이며, 전체 평판이나 현재 상태를 보장하지 않아요. 거리 점수에는 반영하지 않았어요.';
    } else $('reviews-status').textContent = messages[job.error] || '후기 조사를 완료하지 못했어요. 지도 링크에서 직접 살펴볼 수 있어요.';
  } catch(error) { $('reviews-status').textContent = error.message; }
  finally { if(!reviewState.result?.safety&&typeof setSafetyStatus==='function')setSafetyStatus($('reviews-status').textContent);reviewState.job=null; busy(false);if(typeof renderLeisure==='function')renderLeisure(); $('reviews-cancel').hidden=true;
    if (key===reviewState.key) $('reviews-status').textContent += ' 다시 조사하려면 위치 비교를 새로 실행해 주세요.'; }
}
$('reviews-search').addEventListener('click', () => startReviews());
$('reviews-cancel').addEventListener('click', async()=>{
  if (!reviewState.job) return;
  reviewState.cancelled=true; $('reviews-status').textContent='조사 취소를 요청했어요.';
  try {if(reviewState.accepted)await api('/api/jobs/'+reviewState.job+'/cancel',{});}
  catch(error){$('reviews-status').textContent=error.message;}
});
