"""실제 Chromium으로 카드 한 장 렌더링 (Chromium이 설치돼 있을 때만)."""

import pytest
from PIL import Image

from cardnews.errors import AppError
from cardnews.render import card as render

try:
    from cardnews.render.chromium import Browser
    with Browser():
        pass
except (ImportError, AppError):
    pytest.skip("Chromium이 설치돼 있지 않아요", allow_module_level=True)

LAYOUT = {"textArea": "top", "scale": None, "scrim": "auto", "color": "auto"}
TEXTS = {"title": "스킬이 뭔가요", "keyLine": "스킬은 에이전트에게 작업 방법을 알려 주는 폴더예요.",
         "body": "SKILL.md 파일에 필요한 스크립트와 참고 자료를 함께 담아요."}


@pytest.fixture(scope="module")
def browser():
    with Browser() as b:
        yield b


def bg(tmp_path, color=None, busy=False):
    img = Image.new("RGB", (896, 1200), color or (238, 235, 229))
    if busy:  # 글자 자리에 줄무늬를 깔아 물건과 겹친 상황을 만들어요
        for y in range(0, 700, 20):
            img.paste((30, 30, 30), (0, y, 896, y + 10))
    path = tmp_path / "bg.png"
    img.save(path)
    return path


def draw(browser, tmp_path, texts=TEXTS, layout=LAYOUT, **bg_kw):
    return render.render_card(browser, out_stem=tmp_path / "cards" / "card_2.v1", texts=texts,
                              role="body", layout=layout, bg=bg(tmp_path, **bg_kw), disclose=True)


def test_light_background_passes_and_png_is_1080x1350(browser, tmp_path):
    out = draw(browser, tmp_path)
    assert out["checks"]["status"] == "pass", out["checks"]["items"]
    assert out["applied"]["color"] == "dark" and out["autoFixes"] == []
    assert Image.open(out["png"]).size == (1080, 1350)
    assert out["checks"]["minFontPx"] == 32
    assert (tmp_path / "cards" / "card_2.v1.html").exists()


def test_pretendard_is_loaded(browser, tmp_path):
    out = draw(browser, tmp_path)
    page = browser.open(out["png"].with_suffix(".html"))
    assert page.evaluate("document.fonts.check('32px Pretendard')")
    page.close()


def test_dark_background_switches_to_light_text(browser, tmp_path):
    out = draw(browser, tmp_path, color=(35, 35, 40))
    assert out["applied"]["color"] == "light" and out["checks"]["contrastRatio"] >= 4.5


def test_long_text_is_shrunk_and_still_rendered(browser, tmp_path):
    long = {**TEXTS, "body": "아주 긴 본문이에요. " * 40}
    out = draw(browser, tmp_path, texts=long)
    assert any("줄였" in f for f in out["autoFixes"])
    assert out["checks"]["status"] == "fail" and out["checks"]["overflow"] is True  # 줄여도 넘쳐요
    assert Image.open(out["png"]).size == (1080, 1350)  # 그래도 PNG는 만들어요


def test_user_size_is_kept_even_when_it_overflows(browser, tmp_path):
    long = {**TEXTS, "body": "조금 긴 본문이에요. " * 14}
    out = draw(browser, tmp_path, texts=long, layout={**LAYOUT, "scale": 2})
    assert out["applied"]["step"] == 2 and not any("줄였" in f for f in out["autoFixes"])


def test_busy_background_gets_a_scrim(browser, tmp_path):
    out = draw(browser, tmp_path, busy=True)
    assert out["applied"]["scrim"] is True and any("배경" in f for f in out["autoFixes"])
