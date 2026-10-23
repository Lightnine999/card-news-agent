"""제작 run이 쓰는 렌더러. 브라우저는 처음 필요할 때 한 번만 띄우고 run이 끝나면 닫아요.

CARDNEWS_RENDERER=fake면 브라우저 없이 빈 PNG와 "통과" 점검을 돌려줘요(흐름 테스트용).
브라우저를 못 띄우면 남은 카드도 바로 같은 이유로 실패해요(다시 띄워 보며 시간을 쓰지 않게요).
"""

import os
from pathlib import Path

from PIL import Image

from cardnews import config
from cardnews.errors import AppError
from cardnews.render import card, layout as rules


class Renderer:
    def __init__(self) -> None:
        self._browser = None
        self._down: AppError | None = None

    def render(self, **kw) -> dict:
        if config.renderer() == "fake":
            return _fake(**kw)
        if self._down:
            raise self._down
        if self._browser is None:
            from cardnews.render.chromium import Browser
            try:
                self._browser = Browser().__enter__()
            except AppError as err:
                self._down = err
                raise
        try:
            return card.render_card(self._browser, **kw)
        except AppError:
            raise
        except Exception as err:  # 브라우저 안 오류도 카드 실패로 보여 줘요
            raise AppError("RENDER_FAILED", f"글자를 올리다 오류가 났어요: {str(err)[:120]}") from err

    def close(self) -> None:
        if self._browser is not None:
            self._browser.__exit__(None, None, None)
            self._browser = None


def _fake(*, out_stem: Path, texts: dict, role: str, layout: dict, bg, disclose: bool) -> dict:
    if out_stem.name.split(".")[0] in os.environ.get("FAKE_RENDER_FAIL_ON", "").split(","):
        raise AppError("RENDER_FAILED", "모의 렌더러가 일부러 실패했어요.")
    png = out_stem.with_name(out_stem.name + ".png")
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tuple(rules.CARD_SIZE), (240, 238, 233)).save(png)
    settings = {**rules.settings_from(layout), "color": rules.settings_from(layout)["color"] or "dark"}
    checks = {"status": "pass", "overflow": False, "minFontPx": 32, "contrastRatio": 15.0, "busy": 5.0,
              "size": rules.CARD_SIZE, "items": [], "blocks": []}
    return {"png": png, "checks": checks, "applied": settings, "autoFixes": []}
