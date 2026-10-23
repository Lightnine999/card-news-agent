// 화면 상태와 사용자 행동. 화면은 GET /api/projects/{id} 응답만 보고 다시 그려요.
import { api, ApiError } from './api.js';
import * as V from './views.js';

const POLL_MS = 1500;
const RELOAD_CODES = new Set([
  'VERSION_CONFLICT', 'QUESTION_STALE', 'ALREADY_ANSWERED', 'STAGE_CONFLICT', 'IDEMPOTENCY_CONFLICT',
]);
const $app = document.getElementById('app');
const $flash = document.getElementById('flash');

const ui = {
  pending: new Set(),      // 보내는 중인 버튼
  requestIds: {},          // 버튼 하나 = 사용자 행동 하나 = requestId 하나
  drafts: {},              // 입력 중인 글·선택 (다시 그려도 남게)
  selected: new Set(),     // 체크한 후보
  saving: false,
};
let project = null;
let lastShown = '';
let pollTimer = null;
let saveChain = Promise.resolve();

const projectIdFromPath = () => (location.pathname.match(/^\/p\/([\w-]+)/) || [])[1];

function flash(message) {
  $flash.textContent = message;
  $flash.hidden = false;
  clearTimeout(flash.timer);
  flash.timer = setTimeout(() => { $flash.hidden = true; }, 3500);
}

// --- 그리기 ------------------------------------------------------------------

function render() {
  if (!project) return;
  const p = project;
  const parts = [V.headerView(p), V.runView(p.activeRun, ui), V.errorView(p, ui),
    V.questionView(p.currentQuestion, ui)];
  if (p.stage === 'created' && !p.activeRun) parts.push(V.createdView(ui));
  if (p.stage === 'selecting') parts.push(V.selectingView(p, ui));
  if (['deep_researching', 'editing', 'storyboard_review'].includes(p.stage)) parts.push(V.notesView(p));
  if (p.stage === 'storyboard_review') parts.push(V.storyboardView(p, ui));
  if (p.stage === 'producing') parts.push(V.producingView(p, ui));
  parts.push(V.placeholderView(p));
  $app.innerHTML = parts.join('');
}

async function renderHome() {
  const [list, health] = await Promise.all([
    api('GET', '/api/projects'), api('GET', '/api/health').catch(() => null),
  ]);
  $app.innerHTML = V.homeView(list.projects, health, ui);
}

// --- 불러오기·폴링 -------------------------------------------------------------

async function refresh() {
  const id = projectIdFromPath();
  if (!id) return;
  clearTimeout(pollTimer);
  try {
    const next = await api('GET', `/api/projects/${id}`);
    const json = JSON.stringify(next);
    if (!ui.saving) ui.selected = new Set(next.selection.candidateIds);
    project = next;
    if (json !== lastShown) { lastShown = json; render(); }
    if (next.activeRun && ['queued', 'running'].includes(next.activeRun.status)) {
      pollTimer = setTimeout(refresh, POLL_MS);
    }
  } catch (err) {
    $app.innerHTML = `<section class="panel error"><h2>프로젝트를 불러오지 못했어요</h2>
      <p>${err.message}</p><a class="btn" href="/">처음으로</a></section>`;
  }
}

// --- 행동 ------------------------------------------------------------------

// 같은 버튼을 여러 번 눌러도 한 번만 보내요. 끝나면 서버 상태를 다시 읽어요.
async function act(key, send) {
  if (ui.pending.has(key)) return;
  ui.pending.add(key);
  ui.requestIds[key] ||= crypto.randomUUID();
  render();
  try {
    await send(ui.requestIds[key]);
  } catch (err) {
    handleError(err);
  } finally {
    ui.pending.delete(key);
    delete ui.requestIds[key];
    lastShown = '';
    await refresh();
  }
}

function handleError(err) {
  if (!(err instanceof ApiError)) { flash('서버에 연결하지 못했어요. 서버가 켜져 있는지 확인해 주세요.'); return; }
  if (RELOAD_CODES.has(err.code)) { flash(`화면이 바뀌어서 새로 불러왔어요. (${err.message})`); return; }
  flash(err.message);
}

const post = (url, body) => api('POST', url, body);
const base = () => `/api/projects/${project.id}`;

const actions = {
  research: () => act('research', (rid) => post(`${base()}/research`, { requestId: rid })),
  deep: () => act('deep', async (rid) => {
    await saveChain;  // 저장 중인 선택이 끝난 뒤에 보내요
    await post(`${base()}/deep-research`, { version: project.version, requestId: rid });
  }),
  cancel: (el) => act('cancel', () => post(`/api/runs/${el.dataset.run}/cancel`)),
  'resume-restart': (el) => act('resume-restart', (rid) => post(`/api/runs/${el.dataset.run}/resume`, { mode: 'restart', requestId: rid })),
  'resume-continue': (el) => act('resume-continue', (rid) => post(`/api/runs/${el.dataset.run}/resume`, { mode: 'continue', requestId: rid })),
  answer: () => {
    const q = project.currentQuestion;
    const key = `${q.id}:${q.version}`;
    const choice = ui.drafts[`choice:${key}`];
    const answer = choice === '__free' ? { freeText: ui.drafts[`free:${key}`].trim() } : { optionId: choice };
    return act('answer', (rid) => post(`${base()}/answers`, {
      questionId: q.id, version: q.version, answer, requestId: rid,
    }));
  },
  feedback: () => {
    const sb = project.storyboard;
    const instruction = (ui.drafts[`feedback:${sb.version}`] || '').trim();
    return act('feedback', (rid) => post(`${base()}/storyboard/feedback`, { instruction, version: sb.version, requestId: rid }));
  },
  'approve-storyboard': () => act('approve-storyboard', (rid) => post(`${base()}/approve`, {
    stage: 'storyboard', version: project.storyboard.version, requestId: rid,
  })),
  'retry-card': (el) => act(`retry-card:${el.dataset.card}`, (rid) => post(
    `${base()}/cards/${el.dataset.card}/retry`, { resultVersion: Number(el.dataset.version), requestId: rid },
  )),
  create: () => act('create', async (rid) => {
    const form = document.getElementById('create-form');
    if (!form.reportValidity()) return;
    const topic = form.topic.value.trim();
    const periodDays = Number(form.periodDays.value);
    const { projectId } = await post('/api/projects', { topic, periodDays, requestId: rid });
    await post(`/api/projects/${projectId}/research`, { requestId: `${rid}-r`, periodDays });
    ui.drafts.topic = '';
    history.pushState({}, '', `/p/${projectId}`);
  }),
};

// 후보 체크는 누를 때마다 저장해요. 저장은 차례로 보내서 version이 엇갈리지 않게 해요.
function toggleCandidate(input) {
  const id = input.dataset.candidate;
  const next = new Set(ui.selected);
  if (input.checked) next.add(id); else next.delete(id);
  if (next.size > 3) { input.checked = false; flash('최대 3개까지 고를 수 있어요.'); return; }
  ui.selected = next;
  ui.saving = true;
  render();
  saveChain = saveChain.then(async () => {
    try {
      const res = await post(`${base()}/selection`, { candidateIds: [...ui.selected], version: project.version });
      project = { ...project, version: res.version, selection: res.selection };
    } catch (err) {
      handleError(err);
      project = null;  // 서버 상태로 선택을 다시 맞춰요
      await refresh();
    } finally {
      ui.saving = false;
      render();
    }
  });
}

// --- 이벤트 연결 --------------------------------------------------------------

$app.addEventListener('click', (event) => {
  const el = event.target.closest('[data-action]');
  if (!el || el.disabled) return;
  event.preventDefault();
  const [name] = el.dataset.action.split(':');  // retry-card:card_2 처럼 카드마다 따로 잠가요
  actions[name]?.(el);
});

$app.addEventListener('change', (event) => {
  const el = event.target;
  if (el.dataset.candidate) toggleCandidate(el);
  else if (el.type === 'radio' && el.dataset.draft) { ui.drafts[el.dataset.draft] = el.value; render(); }
});

$app.addEventListener('input', (event) => {
  const el = event.target;
  if (el.dataset.draft && el.type !== 'radio') {
    ui.drafts[el.dataset.draft] = el.value;
    let action = 'feedback';
    if (el.dataset.draft.startsWith('free:')) {
      // 직접 입력칸에 쓰면 "직접 입력"을 고른 것으로 봐요
      const key = el.dataset.draft.slice('free:'.length);
      ui.drafts[`choice:${key}`] = '__free';
      const radio = $app.querySelector('input[type="radio"][value="__free"]');
      if (radio) radio.checked = true;
      action = 'answer';
    }
    const button = $app.querySelector(`[data-action="${action}"]`);
    if (button && !ui.pending.has(action)) button.disabled = !el.value.trim();
  }
  if (el.name === 'topic') ui.drafts.topic = el.value;
});

$app.addEventListener('submit', (event) => { event.preventDefault(); actions.create(); });

function route() {
  project = null;
  lastShown = '';
  clearTimeout(pollTimer);
  if (projectIdFromPath()) refresh(); else renderHome();
}

window.addEventListener('popstate', route);
const originalPush = history.pushState.bind(history);
history.pushState = (...args) => { originalPush(...args); route(); };
document.addEventListener('click', (event) => {
  const link = event.target.closest('a[href^="/"]');
  if (!link || event.metaKey || event.ctrlKey) return;
  event.preventDefault();
  history.pushState({}, '', link.getAttribute('href'));
});

route();
