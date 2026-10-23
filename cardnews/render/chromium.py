"""헤드리스 Chromium(Playwright)으로 카드 HTML을 열고, 재고, 찍어요 (D8).

run 하나에서 브라우저를 한 번만 띄우고 카드마다 페이지를 새로 열어요.
"""

import io
from pathlib import Path

from PIL import Image, ImageStat

from cardnews.errors import AppError

VIEWPORT = {"width": 1080, "height": 1350}

APPLY_JS = """(s) => {
  const card = document.querySelector('.card');
  card.dataset.area = s.area; card.dataset.scrim = s.scrim ? 'on' : 'off';
  card.dataset.color = s.color || 'dark'; card.style.setProperty('--step', String(s.step));
}"""

MEASURE_JS = """() => {
  const box = document.querySelector('.text');
  const blocks = [...document.querySelectorAll('[data-block]')].map((el) => {
    const r = el.getBoundingClientRect();
    return { name: el.dataset.block, rect: [r.x, r.y, r.width, r.height].map(Math.round),
             fontPx: parseFloat(getComputedStyle(el).fontSize), wide: el.scrollWidth > el.clientWidth + 1 };
  });
  const overflow = box.scrollHeight > box.clientHeight + 1 || blocks.some((b) => b.wide);
  return { blocks: blocks.map(({ wide, ...b }) => b), overflow };
}"""

FAILED = "글자를 올릴 브라우저(Chromium)를 실행하지 못했어요. README의 설치 안내대로 `uv run playwright install chromium`을 실행해 주세요."


class Browser:
    """with Browser() as b: b.open(path) → Page"""

    def __enter__(self) -> "Browser":
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
        except Exception as err:  # 설치 안 됨·실행 실패를 카드 실패로 보여 줘요
            self.__exit__(None, None, None)
            raise AppError("RENDER_FAILED", FAILED) from err
        return self

    def __exit__(self, *exc) -> None:
        for name, close in (("_browser", "close"), ("_pw", "stop")):
            target = getattr(self, name, None)
            if target is not None:
                try:
                    getattr(target, close)()
                except Exception:
                    pass
                setattr(self, name, None)

    def open(self, html_path: Path):
        page = self._browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(html_path.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        return page


def apply(page, settings: dict) -> None:
    page.evaluate(APPLY_JS, settings)


def measure(page) -> dict:
    """글자 덩어리 위치·크기·넘침, 그리고 글자를 숨긴 배경에서 덩어리 자리의 밝기 평균·표준편차."""
    found = page.evaluate(MEASURE_JS)
    page.evaluate("document.querySelector('.card').classList.add('measure')")
    shot = Image.open(io.BytesIO(page.screenshot())).convert("L")
    page.evaluate("document.querySelector('.card').classList.remove('measure')")
    blocks = []
    for block in found["blocks"]:
        x, y, w, h = block["rect"]
        area = shot.crop((max(x, 0), max(y, 0), min(x + max(w, 1), shot.width), min(y + max(h, 1), shot.height)))
        stat = ImageStat.Stat(area)
        blocks.append({**block, "bgMean": stat.mean[0], "bgStd": stat.stddev[0]})
    return {"blocks": blocks, "overflow": found["overflow"], "size": [shot.width, shot.height]}


def capture(page, png_path: Path) -> list[int]:
    """PNG로 저장하고, 저장한 파일을 다시 열어 실제 크기를 돌려줘요."""
    png_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(png_path))
    with Image.open(png_path) as saved:
        return list(saved.size)
