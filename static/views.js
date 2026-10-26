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
  image_retry: '카드 다시 만들기', render: '글자 올리기', revision: '카드 고치기', export: '내보내기',
};
const GROUP_LABEL = { open: '지금 지원 가능', upcoming: '곧 열릴 예정' };
const HOST_LABEL = { gov: '정부·공공', corp: '대기업', univ: '대학·재단', other: '기타' };

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
        <select name="workflow" aria-label="작업 종류">
          <option value="news">최신 소식</option><option value="support">지원사업·공모전</option>
        </select>
        <input name="topic" maxlength="100" required placeholder="AI 최신소식 / IT·AI 창업 지원사업과 공모전" value="${esc(ui.drafts.topic || '')}">
        <select name="periodDays" aria-label="조사 기간 (최신 소식만)">
          <option value="7">최근 7일</option><option value="30">최근 30일</option>
        </select>
        ${btn('create', '조사 시작', ui, { cls: 'primary' })}
      </form>
      <p class="small muted">지원사업·공모전은 기간을 고르지 않아요. 오늘부터 6개월 안에 지원할 수 있거나 열릴 공고를 찾아요.</p>
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
  const failed = !p.activeRun && ['failed', 'interrupted', 'cancelled'].includes(p.lastRun?.status)
    ? p.lastRun.period : null;
  // 최신 소식은 "최근 7일", 지원사업·공모전은 "오늘부터 6개월"
  const span = (x) => (x.months ? `오늘부터 ${x.months}개월` : `최근 ${x.days}일`);
  let period = '조사 전';
  if (!r?.requestedAt && failed?.requestedAt) {  // 조사를 했지만 끝내지 못한 경우
    period = `조사를 끝내지 못했어요 · ${fmtTime(failed.requestedAt)} 기준 · ${span(failed)}`;
  }
  if (r?.requestedAt) {
    period = `${fmtTime(r.requestedAt)} 기준 · ${span(r.period)} (${fmtDate(r.period.from)} ~ ${fmtDate(r.period.to)})`;
  } else if (running) {
    period = running.requestedAt
      ? `조사 중 · ${fmtTime(running.requestedAt)} 기준 · ${span(running)}`
      : `조사 준비 중 · ${span(running)}`;
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
  // 그림 작업은 남은 카드만 이어서 만들 수 있어요. 엔진 작업은 엔진 세션이 있어야 이어갈 수 있어요.
  const images = ['production', 'image_retry', 'render', 'revision'].includes(run.kind);
  const usable = run.error.nextActions.filter((a) => a !== 'continue' || images || p.engine.sessionId);
  const labelFor = (mode, label) => (images && mode === 'continue' ? '남은 카드만 이어서 만들기'
    : images && mode === 'restart' ? '모든 카드 처음부터' : label);
  const buttons = usable.map((a) => ERROR_BUTTONS[a]).filter(Boolean)
    .filter(([mode]) => !seen.has(mode) && seen.add(mode))
    .map(([mode, label]) => btn(`resume-${mode}`, labelFor(mode, label), ui, { data: `data-run="${esc(run.id)}"` }))
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

// 지원사업·공모전 후보: 금액·대상·마감(D-day는 앱 계산)·주최
function supportWhen(c) {
  if (c.dateStatus === 'confirmed') return `마감 ${esc(c.deadline)}${c.deadlineTime ? ` ${esc(c.deadlineTime)}` : ''} <b>${esc(c.dday || '')}</b>`;
  if (c.dateStatus === 'rolling') return `마감: ${esc(c.rollingText || '상시 모집')}`;
  return `열림 ${esc(c.openMonth)} 예정(미확정) <span class="muted small">근거: ${esc(c.basis)}</span>`;
}

function supportCandidateView(c, ui) {
  const checked = ui.selected.has(c.id);
  const [first, ...more] = c.sources;
  const unopened = (s) => (s.type === 'official' && s.opened === false
    ? ' <span class="badge unverified" title="엔진이 이 페이지를 직접 열어 확인하지 않았어요">출처 미확인</span>' : '');
  const source = (s) => `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>
    <span class="badge gray">${esc(SOURCE_LABEL[s.type] || s.type)}</span>${unopened(s)}`;
  return `
    <article class="cand ${checked ? 'on' : ''}">
      <label class="pick"><input type="checkbox" data-candidate="${esc(c.id)}" ${checked ? 'checked' : ''}>
        <span class="sr">이 공고 고르기</span></label>
      <div>
        <p><span class="badge">${esc(c.kind)}</span> <span class="badge gray">${esc(HOST_LABEL[c.hostType] || c.hostType)}</span></p>
        <h3>${esc(c.title)}</h3>
        <p><b>${esc(c.amountText || '금액 확인 필요')}</b></p>
        <p>대상: ${esc(c.target)}</p>
        <p>${supportWhen(c)}</p>
        <p class="muted small">주최: ${esc(c.host)}</p>
        <p>${source(first)}</p>${more.length ? `<details><summary>다른 출처 ${more.length}개</summary><ul>${more.map((s) => `<li>${source(s)}</li>`).join('')}</ul></details>` : ''}
        <p class="why">고를 만한 이유: ${esc(c.whyPick)}</p>
        <p class="unsure">불확실한 점: ${esc(c.uncertainty)}</p>
      </div>
    </article>`;
}

// 엔진이 넣었지만 게시일이 조사 기간 밖이라 앱이 뺀 후보
function excludedView(excluded, support = false) {
  if (!excluded?.length) return '';
  const rows = excluded.map((e) => `<li>${e.url
    ? `<a href="${esc(safeUrl(e.url))}" target="_blank" rel="noopener noreferrer">${esc(e.title)}</a>`
    : esc(e.title)} <span class="muted">— ${esc(e.reason)}</span></li>`).join('');
  return `
    <div class="excluded">
      <p><b>${support ? `공고 ${excluded.length}개를 뺐어요.` : `조사 기간 밖 후보 ${excluded.length}개를 뺐어요.`}</b>
        <span class="muted">${support ? '이미 마감됐거나, 6개월 밖이거나, 공식 근거를 확인하지 못해서예요.' : '게시일이 조사 기간에 들지 않아서예요.'}</span></p>
      <details><summary>뺀 후보 보기</summary><ul>${rows}</ul></details>
    </div>`;
}

function supportSelectingView(p, ui) {
  const cands = p.research?.candidates || [];
  const count = ui.selected.size;
  const group = (g) => {
    const list = cands.filter((c) => c.group === g);
    return `<h3>${GROUP_LABEL[g]} ${list.length}</h3>
      ${list.length ? `<div class="cands">${list.map((c) => supportCandidateView(c, ui)).join('')}</div>` : '<p class="muted">없어요.</p>'}`;
  };
  return `
    <section class="panel">
      <div class="row"><h2>공고 ${cands.length}개 · 카드로 만들 공고를 1~${p.maxSelection}개 골라 주세요</h2>
        ${btn('research', '다시 조사', ui, { cls: 'ghost' })}</div>
      <p class="small muted">금액이 큰 순서로 놓았어요. D-day는 오늘 기준으로 앱이 계산해요.${p.research?.broadened ? ' 분야·지역을 넓혀서 다시 찾은 결과예요.' : ''}</p>
      ${excludedView(p.research?.excluded, true)}
      ${group('open')}${group('upcoming')}
    </section>
    <div class="sticky">
      <span>${count}개 골랐어요</span>
      ${btn('deep', '공식 공고문 확인하고 카드 만들기', ui, { cls: 'primary', disabled: count < 1 || ui.saving })}
    </div>`;
}

export function selectingView(p, ui) {
  if (p.workflow === 'support') return supportSelectingView(p, ui);
  const cands = p.research?.candidates || [];
  const count = ui.selected.size;
  return `
    <section class="panel">
      <div class="row"><h2>후보 ${cands.length}개 · 1~${p.maxSelection}개 골라 주세요</h2>
        ${btn('research', '다시 조사', ui, { cls: 'ghost' })}</div>
      ${excludedView(p.research?.excluded)}
      <div class="cands">${cands.map((c) => candidateView(c, ui)).join('')}</div>
      <label class="field">독자 메모 <span class="muted small">(선택, 200자까지. 적으면 독자를 따로 묻지 않고 이 독자로 판단해요)</span>
        <input data-draft="audienceNote" maxlength="200" placeholder="예: AI를 처음 접하는 대학생" value="${esc(ui.drafts.audienceNote || '')}"></label>
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
      ${n.notice ? `<p class="small">공고문 확인: ${esc(n.notice.dateStatus)} · 마감/열림 ${esc(n.notice.deadline || n.notice.openMonth || n.notice.rollingText || '미확인')} · 금액 ${esc(n.notice.amountText || '확인 필요')} · 대상 ${esc(n.notice.target)} ${n.notice.officialUrl ? links([n.notice.officialUrl]) : ''}</p>` : ''}
      <p class="small">공식 발표 날짜: ${n.officialDate ? `<b>${esc(n.officialDate)}</b> ${n.officialDateSource ? links([n.officialDateSource]) : ''}` : '<b class="warn-text">미확인</b>'}</p>
      <h4>확인한 사실 (변화·사용 조건)</h4>${list(n.facts, (f) => `<li>${esc(f.text)} ${links(f.sourceUrls)}</li>`)}
      <h4>발표 주체의 주장</h4>${list(n.claims || [], (f) => `<li>${esc(f.text)} ${links(f.sourceUrls)}</li>`)}
      <h4>아직 확인하지 못한 내용</h4>${list(n.limits, (t) => `<li>${esc(t)}</li>`)}
      <h4>서로 다른 내용</h4>${list(n.conflicts, (c) => `<li>${esc(c.text)} ${links(c.sourceUrls)}</li>`)}
      <h4>열지 못한 원문</h4>${list(n.unreachable, (u) => `<li>${esc(u.url)} — ${esc(u.reason)}</li>`)}
    </details>`).join('');
  return `<section class="panel"><h2>조사 기록</h2>${notes}</section>`;
}

// --- 편집 제안 + 스토리보드 (S5) -------------------------------------------------

const FORMAT_LABEL = { list: '목록형', story: '이야기형' };

function formatCompare(e) {
  if (!e.formatComparison?.length) return '';
  const rows = e.formatComparison.map((o) => `
    <tr class="${o.format === e.recommendedFormat ? 'pick' : ''}"><td><b>${FORMAT_LABEL[o.format] || esc(o.format)}</b>${o.format === e.recommendedFormat ? ' ⭐추천' : ''}</td>
      <td>${esc(o.fitsReader)}</td><td>${esc(o.pros)}</td><td>${esc(o.cons)}</td></tr>`).join('');
  return `<div class="table-wrap"><table class="verify"><thead><tr><th>형식</th><th>이 독자에게</th><th>좋은 점</th><th>아쉬운 점</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    ${e.formatReason ? `<p class="small">추천 이유: ${esc(e.formatReason)}</p>` : ''}
    <p class="small muted">${e.latestBasis ? `'최신' 근거: ${esc(e.latestBasis)}` : "제목에 '최신'을 쓰지 않았어요(근거가 없으면 쓰지 않아요)."}</p>`;
}

export function storyboardView(p, ui) {
  const e = p.editorial;
  const sb = p.storyboard;
  if (!sb) return '';
  const decided = e.decidedBy === 'user_answer' ? '답해 주신 내용으로 정했어요' : 'AI가 판단했어요';
  const link = (u, i) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer">출처 ${i + 1}</a>`;
  const rows = sb.cards.map((c) => `
    <tr class="${c.sourceUrls.length ? '' : 'no-source'}">
      <td>${c.order}<br><span class="muted small">${esc(ROLE_LABEL[c.role] || c.role)}</span></td>
      <td><b>${esc(c.title)}</b><br>${esc(c.keyLine)}</td>
      <td class="pre">${esc(c.body || '—')}</td>
      <td>${esc(c.imageRole || '—')}<br><span class="muted small">제목 자리: ${esc(TEXT_AREA_LABEL[c.imagePlan.textArea] || c.imagePlan.textArea)}</span></td>
      <td>${c.sourceUrls.length ? c.sourceUrls.map(link).join('<br>') : '<b>근거 없음</b>'}</td>
    </tr>`).join('');
  return `
    <section class="panel">
      <h2>편집 제안 <span class="muted small">(${decided})</span></h2>
      <dl class="editorial">
        <dt>독자</dt><dd>${esc(e.audience)}</dd>
        <dt>유용한 이유</dt><dd>${esc(e.whyUseful)}</dd>
        <dt>형식</dt><dd>${esc(e.format)}${formatCompare(e)}</dd>
        <dt>후킹 문구</dt><dd><ul>${e.hooks.map((h) => `<li>${esc(h)}</li>`).join('')}</ul></dd>
      </dl>
    </section>
    <section class="panel">
      <h2>스토리보드 v${sb.version} · ${sb.cards.length}장 <span class="muted small">(한 장에 메시지 하나)</span></h2>
      ${p.workflow === 'support' ? '<p class="small muted">공고 카드의 금액·대상·마감 줄과 요약 카드는 공식 공고문 확인 결과로 앱이 채워요. 변경 요청으로는 제목·표지·그림 계획·카드 구성을 바꿀 수 있어요. 마감 줄의 D-day는 글자를 올리는 날 기준으로 다시 계산해요.</p>' : ''}
      ${sb.dropped?.length ? `<p class="small warn-text">공식 공고문으로 다시 확인해서 ${sb.dropped.length}개를 뺐어요: ${sb.dropped.map((d) => `${esc(d.title)} — ${esc(d.reason)}`).join(' / ')}</p>` : ''}
      <div class="table-wrap"><table class="board">
        <thead><tr><th>장</th><th>제목 · 핵심 문장</th><th>본문</th><th>이미지 역할</th><th>출처</th></tr></thead>
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

// --- 제작 (S6) -------------------------------------------------------------------

const CARD_STATUS = {
  pending: '대기', generating_image: '그림 만드는 중', image_ready: '그림 준비됨', rendering: '글자 넣는 중',
  done: '완료', failed: '실패',
};
const CHECK_LABEL = { pass: '점검 통과', warn: '점검 주의', fail: '점검 실패' };

function imageMeta(img) {
  const [w, h] = img.originalSize;
  const size = `${w}×${h} ${esc(img.originalFormat.toUpperCase())}`;
  if (img.origin === 'mock') return `모의 그림 · ${size}`;
  const instead = img.fallbackFrom ? `<br>agy로 못 만들어 대신 그렸어요: ${esc(img.fallbackFrom.message)}` : '';
  return `${esc(img.disclosure)} · ${esc(img.tool)} · ${size}${instead}`;
}

const layoutChecks = (card) => card.checks?.layout || null;

function checkBadge(card) {
  const checks = layoutChecks(card);
  return checks ? `<span class="badge chk-${esc(checks.status)}">${CHECK_LABEL[checks.status]}</span>` : '';
}

function cardButtons(card, version, ui) {
  const data = `data-card="${esc(card.cardId)}" data-version="${version}"`;
  if (card.status === 'failed' && card.error) {
    const label = card.image ? '이 카드 글자 다시 올리기' : '이 카드 다시 만들기';
    return `<p class="card-error">${esc(card.error.message)} <span class="muted">(${esc(card.error.code)})</span></p>
      ${btn(`retry-card:${card.cardId}`, label, ui, { data })}`;
  }
  if (['image_ready', 'done'].includes(card.status) && card.image?.fallbackFrom) {
    return btn(`retry-card:${card.cardId}`, 'agy로 다시 만들기', ui, { data });
  }
  return '';
}

function productionCard(card, sb, version, ui) {
  const plan = sb.cards.find((c) => c.id === card.cardId) || {};
  const src = card.pngUrl || card.imageUrl;
  const busy = ['generating_image', 'rendering'].includes(card.status);
  const thumb = src
    ? `<img src="${esc(src)}" alt="${esc(plan.title || card.cardId)} 카드" loading="lazy">`
    : `<div class="thumb-empty">${busy ? '<span class="spinner"></span>' : ''}${esc(CARD_STATUS[card.status])}</div>`;
  return `
    <article class="prod-card st-${esc(card.status)}">
      <div class="thumb">${thumb}</div>
      <p><b>${plan.order ?? ''}. ${esc(plan.title || card.cardId)}</b></p>
      <p class="muted">${busy ? '<span class="spinner"></span>' : ''}${esc(CARD_STATUS[card.status] || card.status)}${card.cardVersion > 1 ? ` · v${card.cardVersion}` : ''} ${checkBadge(card)}</p>
      ${card.image ? `<p class="small muted">${imageMeta(card.image)}</p>` : ''}
      ${cardButtons(card, version, ui)}
    </article>`;
}

export function producingView(p, ui) {
  const result = p.result;
  if (!result) return '';
  const done = result.cards.filter((c) => c.status === 'done').length;
  const failed = result.cards.filter((c) => c.status === 'failed').length;
  const waiting = result.cards.some((c) => c.image && !['done', 'rendering'].includes(c.status) && c.status !== 'failed');
  const renderBtn = waiting && !p.activeRun
    ? `<div class="row end">${btn('render-pending', '그림 위에 글자 올리기', ui, { cls: 'primary', data: `data-version="${result.version}"` })}</div>` : '';
  return `
    <section class="panel">
      <h2>카드 ${done}/${result.cards.length}장 완성${failed ? ` · 실패 ${failed}장` : ''}</h2>
      <p class="muted">배경 그림을 만든 뒤 제목·핵심·본문을 글자로 따로 올려요. 그림 안에는 글자를 넣지 않아요.</p>
      ${renderBtn}
      <div class="prod-grid">${result.cards.map((c) => productionCard(c, p.storyboard, result.version, ui)).join('')}</div>
    </section>`;
}

// --- 검수 (S7): 휴대폰 미리보기와 글자 조정 ------------------------------------------

const PHONE_WIDTH = 360;
const SCALE_OPTIONS = [['auto', '자동'], ['-2', '아주 작게'], ['-1', '작게'], ['0', '기본'], ['1', '크게'], ['2', '아주 크게']];
const AREA_OPTIONS = [['top', '위'], ['center', '가운데'], ['bottom', '아래']];
const SCRIM_OPTIONS = [['auto', '자동'], ['on', '켜기'], ['off', '끄기']];
const COLOR_OPTIONS = [['auto', '자동'], ['dark', '어둡게'], ['light', '밝게']];
const TEXT_LIMITS = { title: 30, keyLine: 60, body: 160 };
const TEXT_LABEL = { title: '제목', keyLine: '핵심 문장', body: '본문' };
const PROBLEM_LABEL = { small: '글자 작음', contrast: '대비 부족', busy: '그림과 겹침' };

function reviewTile(card, plan, ui) {
  const open = ui.openCard === card.cardId;
  return `
    <button class="review-tile ${open ? 'open' : ''}" data-action="open-card" data-card="${esc(card.cardId)}">
      ${card.pngUrl ? `<img src="${esc(card.pngUrl)}" alt="${esc(plan.title)} 카드">` : `<span class="thumb-empty">${esc(CARD_STATUS[card.status])}</span>`}
      <span class="tile-label">${plan.order}. ${esc(plan.title)} ${checkBadge(card)}</span>
    </button>`;
}

function phoneFrame(card) {
  // 점검에 걸린 글자 자리를 카드 크기에 대한 비율로 표시해요. 틀이 좁아져도 위치가 맞아요.
  const pct = (n, total) => `${(n / total * 100).toFixed(2)}%`;
  const boxes = (layoutChecks(card)?.blocks || []).filter((b) => b.problems.length).map((b) => {
    const [x, y, w, h] = b.rect;
    const label = b.problems.map((k) => PROBLEM_LABEL[k] || k).join(' · ');
    return `<span class="problem-box" style="left:${pct(x, 1080)};top:${pct(y, 1350)};width:${pct(w, 1080)};height:${pct(h, 1350)}" title="${esc(label)}"></span>`;
  }).join('');
  return `
    <figure class="phone">
      <div class="phone-screen" style="width:${PHONE_WIDTH + 20}px">
        <div class="phone-content"><img src="${esc(card.pngUrl)}" alt="휴대폰 너비 ${PHONE_WIDTH}px 미리보기">${boxes}</div>
      </div>
      <figcaption class="small muted">휴대폰 화면 너비 ${PHONE_WIDTH}px. 빨간 테두리는 점검에 걸린 글자예요.</figcaption>
    </figure>`;
}

function select(name, cardId, options, current, ui) {
  const key = `layout:${cardId}:${name}`;
  const value = String(ui.drafts[key] ?? current);
  const opts = options.map(([v, label]) => `<option value="${v}" ${v === value ? 'selected' : ''}>${label}</option>`).join('');
  return `<select data-draft="${esc(key)}" name="${name}">${opts}</select>`;
}

export function currentTexts(card, plan) {
  const lay = card.layout || {};
  return Object.fromEntries(Object.keys(TEXT_LIMITS).map((k) => [k, lay[k] ?? plan[k] ?? '']));
}

function layoutForm(card, plan, version, ui) {
  const lay = card.layout || {};
  const texts = currentTexts(card, plan);
  const names = plan.role === 'cover' ? ['title', 'keyLine'] : ['title', 'keyLine', 'body'];
  const fields = names.map((k) => {
    const key = `layout:${card.cardId}:${k}`;
    const value = ui.drafts[key] ?? texts[k];
    const input = k === 'body'
      ? `<textarea data-draft="${esc(key)}" maxlength="${TEXT_LIMITS[k]}" rows="3">${esc(value)}</textarea>`
      : `<input data-draft="${esc(key)}" maxlength="${TEXT_LIMITS[k]}" value="${esc(value)}">`;
    return `<label class="field">${TEXT_LABEL[k]} <span class="muted small">(${TEXT_LIMITS[k]}자까지)</span>${input}</label>`;
  }).join('');
  return `
    <div class="layout-form">
      <div class="controls">
        <label>글자 위치 ${select('textArea', card.cardId, AREA_OPTIONS, lay.textArea || 'top', ui)}</label>
        <label>글자 크기 ${select('scale', card.cardId, SCALE_OPTIONS, lay.scale ?? 'auto', ui)}</label>
        <label>글자 뒤 배경 ${select('scrim', card.cardId, SCRIM_OPTIONS, lay.scrim || 'auto', ui)}</label>
        <label>글자 색 ${select('color', card.cardId, COLOR_OPTIONS, lay.color || 'auto', ui)}</label>
      </div>
      ${fields}
      ${lay.textEdited ? '<p class="small warn-text">문구를 스토리보드와 다르게 고쳤어요. 사실·출처 점검에서 다시 봐요.</p>' : ''}
      <div class="row end">${btn(`apply-layout:${card.cardId}`, '이 카드에 적용', ui, { cls: 'primary', data: `data-card="${esc(card.cardId)}" data-version="${version}"` })}</div>
      <p class="small muted">적용하면 이 카드만 글자를 다시 올려요. 배경 그림과 다른 카드는 그대로예요.</p>
    </div>`;
}

function cardDetail(card, plan, version, ui) {
  const checks = layoutChecks(card);
  const items = checks?.items?.length
    ? `<ul class="check-items">${checks.items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul>`
    : '<p class="ok">잘림·크기·대비·겹침 점검을 모두 통과했어요.</p>';
  const fixes = card.render?.autoFixes?.length
    ? `<p class="small muted">자동으로 고친 것: ${card.render.autoFixes.map(esc).join(' → ')}</p>` : '';
  const numbers = checks
    ? `<p class="small muted">가장 작은 글자 ${checks.minFontPx}px · 대비 ${checks.contrastRatio}:1 · 얼룩짐 ${checks.busy} · ${checks.size.join('×')}</p>` : '';
  return `
    <section class="panel card-detail">
      <div class="row"><h2>${plan.order}. ${esc(plan.title)} ${checkBadge(card)}</h2>
        <span class="muted small">v${card.cardVersion}</span></div>
      ${card.status !== 'done' ? `<p class="muted">${esc(CARD_STATUS[card.status])}</p>${cardButtons(card, version, ui)}` : ''}
      ${card.pngUrl ? `<div class="preview-pair">
        <figure class="original"><img src="${esc(card.pngUrl)}" alt="원본 1080×1350"><figcaption class="small muted">원본 1080×1350 (축소)</figcaption></figure>
        ${phoneFrame(card)}</div>` : ''}
      ${items}${fixes}${numbers}
      ${card.image ? layoutForm(card, plan, version, ui) : ''}
    </section>`;
}

const SCOPE_OPTIONS = [['auto', 'AI가 판단'], ['text', '글자만 고치기'], ['image', '그림도 다시 만들기']];

function revisionPanel(p, plans, ui) {
  const result = p.result;
  const chosen = ui.reviseCards;
  const scope = ui.drafts['revise:scope'] || 'auto';
  const instruction = ui.drafts['revise:instruction'] || '';
  const boxes = result.cards.map((c) => `
    <label class="pick-card"><input type="checkbox" data-revise-card="${esc(c.cardId)}" ${chosen.has(c.cardId) ? 'checked' : ''}
      ${c.image ? '' : 'disabled'}> ${plans[c.cardId].order}. ${esc(plans[c.cardId].title)}</label>`).join('');
  const radios = SCOPE_OPTIONS.map(([v, label]) => `
    <label><input type="radio" name="revise-scope" value="${v}" data-draft="revise:scope" ${v === scope ? 'checked' : ''}> ${label}</label>`).join('');
  const ready = chosen.size > 0 && instruction.trim();
  return `
    <section class="panel">
      <h2>카드 골라 고치기</h2>
      <p class="muted small">고른 카드만 고쳐요. 나머지 카드는 그대로예요. 예: "3번 카드의 본문이 길어. 핵심 조건을 유지하며 두 문장으로 줄여 줘"</p>
      <div class="pick-cards">${boxes}</div>
      <textarea data-draft="revise:instruction" maxlength="500" rows="3" placeholder="무엇을 어떻게 고칠지 적어 주세요">${esc(instruction)}</textarea>
      <div class="scope">그림: ${radios}</div>
      <div class="row end">
        <span class="small muted">${p.finalApproval ? '수정하면 최종 승인이 풀리고, 다시 승인해야 내려받을 수 있어요.' : '수정하면 최종 승인을 다시 받아야 해요.'}</span>
        ${btn('revise', '선택한 카드만 수정', ui, { cls: 'primary', disabled: !ready || !!p.activeRun, data: `data-version="${result.version}"` })}
      </div>
    </section>`;
}

function approvePanel(p, ui) {
  const cards = p.result.cards;
  const notDone = cards.filter((c) => c.status !== 'done').length;
  const failed = cards.filter((c) => layoutChecks(c)?.status === 'fail').length;
  const warned = cards.filter((c) => layoutChecks(c)?.status === 'warn').length;
  const blocked = notDone ? `완료되지 않은 카드가 ${notDone}장 있어요.` : failed ? `가독성 점검에 실패한 카드가 ${failed}장 있어요. 고친 뒤 승인할 수 있어요.` : '';
  return `
    <section class="panel">
      <div class="row"><h2>최종 승인</h2>
        ${btn('approve-final', `v${p.result.version} 최종 승인`, ui, { cls: 'primary', disabled: !!blocked || !!p.activeRun, data: `data-version="${p.result.version}"` })}</div>
      <p class="small ${blocked ? 'warn-text' : 'muted'}">${esc(blocked || `승인하면 카드 PNG·ZIP·출처 기록·이미지 사용 기록을 만들고 다시 열어 검사해요.${warned ? ` 점검 '주의' 카드 ${warned}장이 있어요.` : ''}`)}</p>
    </section>`;
}

const VERIFY_LABEL = { pass: '통과', fail: '실패', needs_check: '확인 필요' };

export function finalView(p) {
  const ex = p.exports;
  const head = `<p>v${p.finalApproval.resultVersion}을 ${fmtTime(p.finalApproval.approvedAt)}에 최종 승인했어요.</p>`;
  if (!ex) return `<section class="panel">${head}<p class="muted">내보내기 파일을 만드는 중이에요.</p></section>`;
  const v = ex.verify;
  const files = ex.files.map((f) => `<li><a href="${esc(f.url)}" download>${esc(f.name)}</a> <span class="muted small">${Math.max(1, Math.round(f.bytes / 1024))}KB</span></li>`).join('');
  const todo = v.items.filter((i) => i.status !== 'pass').map((i) => `
    <li><b>${esc(i.check)} · ${esc(i.target)}</b> <span class="badge vb-${esc(i.status)}">${VERIFY_LABEL[i.status]}</span><br>
      ${esc(i.detail)}<br><span class="small">확인할 것: ${esc(i.whatToCheck || '')}</span></li>`).join('');
  const rows = v.items.map((i) => `
    <tr class="vr-${esc(i.status)}"><td>${esc(i.check)}</td><td>${esc(i.target)}</td>
      <td><span class="badge vb-${esc(i.status)}">${VERIFY_LABEL[i.status]}</span></td>
      <td>${esc(i.detail)}${i.whatToCheck ? `<br><b class="small">확인할 것:</b> <span class="small">${esc(i.whatToCheck)}</span>` : ''}</td></tr>`).join('');
  return `
    <section class="panel">
      <h2>내려받기</h2>${head}
      <ul class="downloads">${files}</ul>
    </section>
    <section class="panel">
      <h2>내보낸 파일 검사</h2>
      <p>통과 ${v.pass} · <span class="warn-text">실패 ${v.fail}</span> · <b>사용자 확인 필요 ${v.needs_check}</b></p>
      <p class="small muted">ZIP을 다시 열어 누락·크기·글자 잘림·출처·날짜를 봤어요. 확인하지 못한 항목은 통과로 적지 않았어요.</p>
      ${todo.length ? `<h3>직접 확인해 주세요</h3><ol class="todo">${todo}</ol>` : ''}
      <div class="table-wrap"><table class="verify"><thead><tr><th>항목</th><th>대상</th><th>결과</th><th>내용</th></tr></thead><tbody>${rows}</tbody></table></div>
    </section>`;
}

export function reviewingView(p, ui) {
  const result = p.result;
  if (!result) return '';
  const plans = Object.fromEntries(p.storyboard.cards.map((c) => [c.id, c]));
  const counts = { pass: 0, warn: 0, fail: 0 };
  result.cards.forEach((c) => { const s = layoutChecks(c)?.status; if (s) counts[s] += 1; });
  const open = result.cards.find((c) => c.cardId === ui.openCard) || result.cards[0];
  return `
    <section class="panel">
      <h2>검수 · 카드 ${result.cards.length}장</h2>
      <p class="muted">점검 통과 ${counts.pass} · 주의 ${counts.warn} · 실패 ${counts.fail}. 카드를 누르면 휴대폰 크기로 보고 글자를 고칠 수 있어요.</p>
      <div class="review-grid">${result.cards.map((c) => reviewTile(c, plans[c.cardId], { ...ui, openCard: open.cardId })).join('')}</div>
    </section>
    ${cardDetail(open, plans[open.cardId], result.version, ui)}
    ${revisionPanel(p, plans, ui)}
    ${p.stage === 'reviewing' ? approvePanel(p, ui) : ''}`;
}

export function placeholderView(p) {
  const text = {
    created: '아직 조사를 시작하지 않았어요.',
  }[p.stage];
  return text ? `<section class="panel notice">${esc(text)}</section>` : '';
}

export function createdView(ui) {
  return `<section class="panel notice">아직 조사를 시작하지 않았어요.
    <div class="row end">${btn('research', '조사 시작', ui, { cls: 'primary' })}</div></section>`;
}
