"""카드 한 장의 HTML. 배경 그림 위에 제목·핵심·본문을 글자로 올려요 (그림 안에 글자를 그리지 않아요).

설정(위치·크기 단계·깔개·글자 색)은 .card의 data 속성과 --step 변수라서, 브라우저가 페이지를 다시 열지 않고
자동 고침을 바로 적용할 수 있어요.
"""

from html import escape

from cardnews import config

FONT_DIR = config.ROOT / "static" / "fonts"
FONTS = ((400, "Pretendard-Regular.woff2"), (600, "Pretendard-SemiBold.woff2"), (700, "Pretendard-Bold.woff2"))
SIZES = {"cover": {"title": 72, "keyLine": 40}, "body": {"title": 64, "keyLine": 44, "body": 32}}
STEP = 0.08  # 크기 한 단계 = 8%

CSS = """
html, body { margin: 0; width: 1080px; height: 1350px; overflow: hidden; }
.card { position: relative; width: 1080px; height: 1350px; overflow: hidden; background: #f3f1ec;
  font-family: Pretendard, sans-serif; word-break: keep-all; overflow-wrap: break-word; --step: 0; }
.bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.scrim { position: absolute; left: 0; right: 0; display: none; --tint: rgba(255,255,255,.7); }
.card[data-color=light] .scrim { --tint: rgba(0,0,0,.55); }
.card[data-scrim=on] .scrim { display: block; }
.card[data-area=top] .scrim { top: 0; height: 64%; background: linear-gradient(var(--tint) 55%, transparent); }
.card[data-area=bottom] .scrim { bottom: 0; height: 64%; background: linear-gradient(transparent, var(--tint) 45%); }
.card[data-area=center] .scrim { top: 18%; height: 64%;
  background: linear-gradient(transparent, var(--tint) 25%, var(--tint) 75%, transparent); }
.safe { position: absolute; left: 88px; right: 88px; top: 96px; bottom: 96px; display: flex; flex-direction: column; }
.card[data-area=top] .safe { justify-content: flex-start; }
.card[data-area=center] .safe { justify-content: center; }
.card[data-area=bottom] .safe { justify-content: flex-end; }
.text { max-height: 700px; overflow: hidden; text-align: center; line-height: 1.4; color: #151515; }
.card[data-color=light] .text, .card[data-color=light] .ai { color: #f4f2ee; }
.text > div + div { margin-top: 28px; }
.title { font-weight: 700; line-height: 1.25; }
.keyLine { font-weight: 600; }
.body { font-weight: 400; white-space: pre-line; }  /* 공고 카드의 대상·마감·신청 세 줄 */
.ai { position: absolute; right: 28px; bottom: 22px; font-size: 20px; color: #151515; opacity: .6; }
.card.measure .text, .card.measure .ai { visibility: hidden; }
"""


def _font_faces() -> str:
    return "\n".join(f"@font-face {{ font-family: Pretendard; font-weight: {w}; "
                     f"src: url('{(FONT_DIR / name).as_uri()}') format('woff2'); }}" for w, name in FONTS)


def _size_css(role: str) -> str:
    sizes = SIZES["cover" if role == "cover" else "body"]
    rules = []
    for name, px in sizes.items():
        scaled = f"calc({px}px * (1 + {STEP} * var(--step)))"
        size = f"max(32px, {scaled})" if name == "body" else scaled  # 본문은 32px 밑으로 내리지 않아요
        rules.append(f".{name} {{ font-size: {size}; }}")
    return "\n".join(rules)


def blocks_for(texts: dict, role: str) -> list[tuple[str, str]]:
    """올릴 글자 덩어리. 표지는 제목·핵심, 나머지는 제목·핵심·본문(본문이 있으면)."""
    names = ("title", "keyLine") if role == "cover" else ("title", "keyLine", "body")
    return [(n, texts[n]) for n in names if texts.get(n)]


def build_html(texts: dict, settings: dict, bg_url: str | None, role: str, disclose: bool) -> str:
    blocks = "".join(f'<div class="{n}" data-block="{n}">{escape(t)}</div>' for n, t in blocks_for(texts, role))
    bg = f'<img class="bg" src="{escape(bg_url)}" alt="">' if bg_url else ""
    ai = '<div class="ai">AI 생성 이미지</div>' if disclose else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>card</title>
<style>{_font_faces()}{CSS}{_size_css(role)}</style></head>
<body><div class="card" data-area="{escape(settings['area'])}" data-scrim="{'on' if settings['scrim'] else 'off'}"
 data-color="{escape(settings['color'] or 'dark')}" style="--step: {int(settings['step'])}">
{bg}<div class="scrim"></div><div class="safe"><div class="text">{blocks}</div></div>{ai}
</div></body></html>"""
