// 서버 호출과 공통 도우미. 화면 상태는 늘 서버 응답에서 다시 그려요.

export class ApiError extends Error {
  constructor(error, status) {
    super(error.message);
    this.code = error.code;
    this.nextActions = error.nextActions || [];
    this.details = error.details || {};
    this.status = status;
  }
}

async function send(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(data.error || { code: 'INTERNAL_ERROR', message: '서버 응답을 읽지 못했어요.' }, res.status);
  }
  return data;
}

// 네트워크가 끊기면 한 번 더 보내요. 본문의 requestId가 같아서 중복 실행되지 않아요.
export async function api(method, url, body) {
  try {
    return await send(method, url, body);
  } catch (err) {
    if (err instanceof TypeError) return send(method, url, body);
    throw err;
  }
}

export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));

export const safeUrl = (url) => (/^https?:\/\//i.test(url || '') ? url : '#');

const timeFmt = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
});
const dateFmt = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
});

export const fmtTime = (iso) => (iso ? timeFmt.format(new Date(iso)) : '');
export const fmtDate = (iso) => (iso ? dateFmt.format(new Date(iso)) : '');
