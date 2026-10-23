// 단계별 화면 조각 (SCREEN_FLOW S0~S5). 모든 글자는 esc()를 거쳐요.
import { esc, safeUrl, fmtTime, fmtDate } from './api.js';

const STAGES = [
  ['created', '주제'], ['researching', '조사'], ['selecting', '선택'],
  ['deep_researching', '심층 조사'], ['editing', '편집 판단'], ['storyboard_review', '스토리보드'],
  ['producing', '제작'], ['reviewing', '검수'], ['final_approved', '완료'],
];
const STATUS_LABEL = { released: '출시됨', announced: '발표만 됨', claimed: '업체 주장', unknown: '확인 중' };
const SOURCE_LABEL = { official: '공식', paper: '논문', press: '언론', blog: '블로그', unknown: '미분류' };
const TEXT_AREA_LABEL = { top: '위쪽', bottom: '아래쪽', center: '가운데' };
const ROLE_LABEL = { cover: '표지', body: '본문', summary: '요약', next_action: '다음 행동' };
const KIND_LABEL = {
  research: '넓은 조사', deep_research: '심층 조사', storyboard: '스토리보드 수정', production: '제작',
};
const MAX_SELECTION = 3;

const btn = (action, label, ui, { cls = '', disabled = false, data = '' } = {}) => {
  const busy = ui.pending.has(action);
  return `<button class="btn ${cls}" data-action="${action}" ${data} ${busy || disabled ? 'disabled' : ''}>`
    + `${busy ? '보내는 중…' : esc(label)}</button>`;
};

// --- 시작 화면 (S0) ---------------------------------------------------------

function healthLine(health) {
  if (!health) return '';
  const item = (ok, label) => `<span class="${ok ? 'ok' : 'warn'}">${ok ? '✓' : '✕'} ${label}</span>`;
  return `<p class="health">엔진: <b>${esc(health.engine)}</b> ·
    ${item(health.claude, 'Claude CLI')} ${item(health.agy, 'agy')}
    ${item(health.chromium, '브라우저 렌더러')} ${item(health.font, '글꼴')}</p>`;
}

export function homeView(projects, health, ui) {
  const rows = projects.map((p) => `
    <li><a href="/p/${esc(p.id)}">${esc(p.topic)}</a>
      <span class="muted">${fmtTime(p.createdAt)} · ${esc(stageLabel(p.stage))}</span>
      ${p.isMock ? '<span class="badge mock">모의</span>' : ''}
      ${p.waitingForUser ? '<span class="badge wait">답변 기다리는 중</span>' : ''}</li>`).join('');
  return `
    <section class="panel">
      <h1>주제를 입력해 주세요</h1>
      <form id="create-form" class="create">
        <input name="topic" maxlength="100" required placeholder="AI 최신소식" value="${esc(ui.drafts.topic || '')}">
        <select name="periodDays" aria-label="조사 기간">
          <option value="7">최근 7일</option><option value="30">최근 30일</option>
        </select>
        ${btn('create', '조사 시작', ui, { cls: 'primary' })}
      </form>
      ${healthLine(health)}
    </section>
    <section class="panel"><h2>이전 프로젝트</h2>
      ${rows ? `<ul class="projects">${rows}</ul>` : '<p class="muted">아직 없어요.</p>'}
    </section>`;
}

const stageLabel = (stage) => (STAGES.find(([s]) => s === stage) || [stage, stage])[1];

// --- 위쪽 띠 -----------------------------------------------------------------

export function headerView(p) {
  const idx = STAGES.findIndex(([s]) => s === p.stage);
  const dots = STAGES.map(([, label], i) =>
    `<li class="${i < idx ? 'done' : i === idx ? 'now' : ''}">${label}</li>`).join('');
  const r = p.research;
  const running = p.activeRun?.period;
  let period = '조사 전';
  if (r?.requestedAt) {
    period = `${fmtTime(r.requestedAt)} 기준 · 최근 ${r.period.days}일 (${fmtDate(r.period.from)} ~ ${fmtDate(r.period.to)})`;
  } else if (running) {
    period = running.requestedAt
      ? `조사 중 · ${fmtTime(running.requestedAt)} 기준 · 최근 ${running.days}일`
      : `조사 준비 중 · 최근 ${running.days}일`;
  }
  return `
    ${p.isMock ? '<div class="mock-band">모의 데이터예요. 실제 검색 결과가 아니에요.</div>' : ''}
    <section class="band">
      <h1>${esc(p.topic)}</h1>
      <p class="muted">${esc(period)}</p>
      <ol class="stages">${dots}</ol>
    </section>`;
}

// --- 진행·오류·질문 ------------------------------------------------------------

export function runView(run, ui) {
  if (!run || !['queued', 'running'].includes(run.status)) return '';
  const lines = run.progress.slice(-5).map((e) =>
    `<li><span class="muted">${fmtTime(e.at).slice(-5)}</span> ${esc(e.message)}</li>`).join('');
  return `
    <section class="panel running">
      <div class="row"><h2><span class="spinner"></span>${esc(KIND_LABEL[run.kind] || run.kind)} 진행 중</h2>
        ${btn('cancel', '취소', ui, { cls: 'ghost', data: `data-run="${esc(run.id)}"` })}</div>
      <ul class="progress">${lines || '<li class="muted">작업 프로세스가 곧 시작해요…</li>'}</ul>
    </section>`;
}

const ERROR_BUTTONS = {
  retry: ['restart', '다시 시도'], restart: ['restart', '이 단계 처음부터'],
  continue: ['continue', '이어서 하기'], login: null, install: null,
};

export function errorView(p, ui) {
  const run = p.lastRun;
  if (p.activeRun || !run) return '';
  if (run.status === 'cancelled') {
    return '<section class="panel notice">작업을 취소했어요. 필요하면 다시 시작해 주세요.</section>';
  }
  if (!['failed', 'interrupted'].includes(run.status) || !run.error) return '';
  const seen = new Set();
  // 엔진 세션이 없으면 이어갈 수 없어서 "이어서 하기"는 숨겨요
  const usable = run.error.nextActions.filter((a) => a !== 'continue' || p.engine.sessionId);
  const buttons = usable.map((a) => ERROR_BUTTONS[a]).filter(Boolean)
    .filter(([mode]) => !seen.has(mode) && seen.add(mode))
    .map(([mode, label]) => btn(`resume-${mode}`, label, ui, { data: `data-run="${esc(run.id)}"` }))
    .join('');
  const hint = run.error.nextActions.includes('login')
    ? '<p>터미널에서 로그인한 뒤 다시 시도해 주세요.</p>' : '';
  return `
    <section class="panel error">
      <h2>${esc(KIND_LABEL[run.kind] || run.kind)} 단계를 끝내지 못했어요</h2>
      <p>${esc(run.error.message)} <span class="muted">(${esc(run.error.code)})</span></p>${hint}
      <div class="row">${buttons}</div>
    </section>`;
}

export function questionView(q, ui) {
  if (!q) return '';
  const key = `${q.id}:${q.version}`;
  const chosen = ui.drafts[`choice:${key}`];
  const options = q.options.map((o) => `
    <label class="option">
      <input type="radio" name="answer" value="${esc(o.id)}" data-draft="choice:${esc(key)}" ${chosen === o.id ? 'checked' : ''}>
      <b>${esc(o.label)}</b>${o.id === q.recommendedOptionId ? ' <span class="badge rec">⭐ 추천</span>' : ''}
      <span class="muted">${esc(o.description)}</span>
    </label>`).join('');
  const free = q.allowFreeText ? `
    <label class="option">
      <input type="radio" name="answer" value="__free" data-draft="choice:${esc(key)}" ${chosen === '__free' ? 'checked' : ''}>
      <b>직접 입력</b>
      <input class="free" maxlength="300" data-draft="free:${esc(key)}" value="${esc(ui.drafts[`free:${key}`] || '')}">
    </label>` : '';
  const canSend = chosen && (chosen !== '__free' || (ui.drafts[`free:${key}`] || '').trim());
  return `
    <section class="panel question">
      <h2>${esc(q.prompt)}</h2>
      <div class="options">${options}${free}</div>
      ${q.recommendationReason ? `<p class="muted">추천 이유: ${esc(q.recommendationReason)}</p>` : ''}
      <div class="row end">${btn('answer', '답변 보내기', ui, { cls: 'primary', disabled: !canSend })}</div>
    </section>`;
}

// --- 후보 선택 (S2) ------------------------------------------------------------

function candidateView(c, ui) {
  const checked = ui.selected.has(c.id);
  const date = (d, label) => (d ? `${label} ${esc(d)}` : '');
  const dates = c.dateStatus === 'unverified'
    ? '<span class="badge gray">날짜 미확인</span>'
    : [date(c.publishedAt, '게시'), date(c.eventDate, '발생')].filter(Boolean).join(' · ');
  const [first, ...more] = c.sources;
  // 공식이라고 적혀 있어도 엔진이 직접 열어 보지 않은 출처는 따로 표시해요
  const unopened = (s) => (s.type === 'official' && s.opened === false
    ? ' <span class="badge unverified" title="엔진이 이 페이지를 직접 열어 확인하지 않았어요">출처 미확인</span>' : '');
  const source = (s) => `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>
    <span class="badge gray">${esc(SOURCE_LABEL[s.type] || s.type)}</span>${unopened(s)}`;
  const merged = more.length ? `<details><summary>같은 발표 기사 ${c.sources.length}개</summary>
    <ul>${more.map((s) => `<li>${source(s)}</li>`).join('')}</ul></details>` : '';
  return `
    <article class="cand ${checked ? 'on' : ''}">
      <label class="pick"><input type="checkbox" data-candidate="${esc(c.id)}" ${checked ? 'checked' : ''}>
        <span class="sr">이 후보 고르기</span></label>
      <div>
        <p><span class="badge">${esc(c.category)}</span> <span class="badge st-${esc(c.status)}">${esc(STATUS_LABEL[c.status] || c.status)}</span></p>
        <h3>${esc(c.title)}</h3>
        <p>${esc(c.summary)}</p>
        <p class="muted">${dates}</p>
        <p>${source(first)}</p>${merged}
        <p class="why">고를 만한 이유: ${esc(c.whyPick)}</p>
        <p class="unsure">불확실한 점: ${esc(c.uncertainty)}</p>
      </div>
    </article>`;
}

// 엔진이 넣었지만 게시일이 조사 기간 밖이라 앱이 뺀 후보
function excludedView(excluded) {
  if (!excluded?.length) return '';
  const rows = excluded.map((e) => `<li>${e.url
    ? `<a href="${esc(safeUrl(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.title)}</a>`
    : esc(e.title)} <span class="muted">— ${esc(e.reason)}</span></li>`).join('');
  return `
    <div class="excluded">
      <p><b>조사 기간 밖 후보 ${excluded.length}개를 뺐어요.</b>
        <span class="muted">게시일이 조사 기간에 들지 않아서예요.</span></p>
      <details><summary>뺀 후보 보기</summary><ul>${rows}</ul></details>
    </div>`;
}

export function selectingView(p, ui) {
  const cands = p.research?.candidates || [];
  const count = ui.selected.size;
  return `
    <section class="panel">
      <div class="row"><h2>후보 ${cands.length}개 · 1~${MAX_SELECTION}개 골라 주세요</h2>
        ${btn('research', '다시 조사', ui, { cls: 'ghost' })}</div>
      ${excludedView(p.research?.excluded)}
      <div class="cands">${cands.map((c) => candidateView(c, ui)).join('')}</div>
    </section>
    <div class="sticky">
      <span>${count}개 골랐어요</span>
      ${btn('deep', '다음 단계', ui, { cls: 'primary', disabled: count < 1 || ui.saving })}
    </div>`;
}

// --- 조사 기록 (S3) ------------------------------------------------------------

export function notesView(p) {
  if (!p.researchNotes?.length) return '';
  const titles = Object.fromEntries((p.research?.candidates || []).map((c) => [c.id, c.title]));
  const links = (urls) => urls.map((u) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer">출처</a>`).join(' ');
  const list = (items, fn) => (items.length ? `<ul>${items.map(fn).join('')}</ul>` : '<p class="muted">없음</p>');
  const notes = p.researchNotes.map((n) => `
    <details class="note"><summary>${esc(titles[n.candidateId] || n.candidateId)}</summary>
      <h4>확인된 사실</h4>${list(n.facts, (f) => `<li>${esc(f.text)} ${links(f.sourceUrls)}</li>`)}
      <h4>한계</h4>${list(n.limits, (t) => `<li>${esc(t)}</li>`)}
      <h4>서로 다른 내용</h4>${list(n.conflicts, (c) => `<li>${esc(c.text)} ${links(c.sourceUrls)}</li>`)}
      <h4>열지 못한 원문</h4>${list(n.unreachable, (u) => `<li>${esc(u.url)} — ${esc(u.reason)}</li>`)}
    </details>`).join('');
  return `<section class="panel"><h2>조사 기록</h2>${notes}</section>`;
}

// --- 편집 제안 + 스토리보드 (S5) -------------------------------------------------

export function storyboardView(p, ui) {
  const e = p.editorial;
  const sb = p.storyboard;
  if (!sb) return '';
  const decided = e.decidedBy === 'user_answer' ? '답해 주신 내용으로 정했어요' : 'AI가 판단했어요';
  const rows = sb.cards.map((c) => `
    <tr class="${c.sourceUrls.length ? '' : 'no-source'}">
      <td>${c.order}</td><td>${esc(ROLE_LABEL[c.role] || c.role)}</td>
      <td>${esc(c.title)}</td><td>${esc(c.keyLine)}</td>
      <td>${c.sourceUrls.length ? c.sourceUrls.map((u) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer">링크</a>`).join(' ') : '<b>근거 없음</b>'}</td>
      <td>${esc(c.imagePlan.kind === 'generated' ? '생성' : c.imagePlan.kind)} / 글자 ${esc(TEXT_AREA_LABEL[c.imagePlan.textArea] || c.imagePlan.textArea)}</td>
    </tr>`).join('');
  return `
    <section class="panel">
      <h2>편집 제안 <span class="muted small">(${decided})</span></h2>
      <dl class="editorial">
        <dt>독자</dt><dd>${esc(e.audience)}</dd>
        <dt>유용한 이유</dt><dd>${esc(e.whyUseful)}</dd>
        <dt>형식</dt><dd>${esc(e.format)}</dd>
        <dt>후킹 문구</dt><dd><ul>${e.hooks.map((h) => `<li>${esc(h)}</li>`).join('')}</ul></dd>
      </dl>
    </section>
    <section class="panel">
      <h2>스토리보드 v${sb.version} · ${sb.cards.length}장</h2>
      <div class="table-wrap"><table class="board">
        <thead><tr><th>장</th><th>역할</th><th>제목</th><th>핵심 문장</th><th>근거</th><th>그림</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <label class="feedback">변경 요청
        <textarea maxlength="500" data-draft="feedback:${sb.version}" placeholder="예: 표지 문장을 더 짧게">${esc(ui.drafts[`feedback:${sb.version}`] || '')}</textarea>
      </label>
      <div class="row end">
        ${btn('feedback', '변경 요청 보내기', ui, { cls: 'ghost', disabled: !(ui.drafts[`feedback:${sb.version}`] || '').trim() })}
        ${btn('approve-storyboard', '이대로 승인하고 제작', ui, { cls: 'primary' })}
      </div>
    </section>`;
}

export function placeholderView(p) {
  const text = {
    created: '아직 조사를 시작하지 않았어요.',
    producing: '이미지 제작과 글자 렌더링은 구현 4~5단계에서 연결해요.',
    reviewing: '검수 화면은 구현 5단계에서 연결해요.',
    final_approved: '내려받기 화면은 구현 5단계에서 연결해요.',
  }[p.stage];
  return text ? `<section class="panel notice">${esc(text)}</section>` : '';
}

export function createdView(ui) {
  return `<section class="panel notice">아직 조사를 시작하지 않았어요.
    <div class="row end">${btn('research', '조사 시작', ui, { cls: 'primary' })}</div></section>`;
}
