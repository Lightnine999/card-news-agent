"""글자 점검 판정과 자동 고침 규칙 (브라우저 없이, 측정값을 직접 넣어요)."""

import pytest

from cardnews.render import layout as L


def measure(mean=235.0, std=8.0, font=(64, 44, 32), overflow=False, size=(1080, 1350)):
    names = ("title", "keyLine", "body")
    blocks = [{"name": n, "rect": [88, 96 + i * 120, 904, 100], "fontPx": f, "bgMean": mean, "bgStd": std}
              for i, (n, f) in enumerate(zip(names, font))]
    return {"blocks": blocks, "overflow": overflow, "size": list(size)}


def settings(**kw):
    return {"area": "top", "step": 0, "scrim": False, "color": "dark", **kw}


def test_contrast_ratio_black_on_white_is_21():
    assert L.contrast_ratio(0, 255) == pytest.approx(21.0, abs=0.1)


def test_pick_color_by_background_brightness():
    assert L.pick_color(230) == "dark" and L.pick_color(60) == "light"


def test_clean_card_passes():
    checks = L.evaluate(measure(), settings())
    assert checks["status"] == "pass" and checks["minFontPx"] == 32 and checks["size"] == [1080, 1350]
    assert checks["contrastRatio"] >= 4.5 and checks["items"] == []


@pytest.mark.parametrize("m,word", [
    (measure(overflow=True), "잘림"),
    (measure(font=(64, 44, 28)), "글자 크기"),
    (measure(mean=120), "대비"),
    (measure(size=(1080, 1080)), "크기"),
])
def test_failures(m, word):
    checks = L.evaluate(m, settings())
    assert checks["status"] == "fail" and any(word in i for i in checks["items"])


def test_busy_background_is_a_warning():
    checks = L.evaluate(measure(std=40), settings())
    assert checks["status"] == "warn" and any("겹" in i for i in checks["items"])
    assert any("busy" in b["problems"] for b in checks["blocks"])  # 화면에서 빨간 테두리로 표시할 덩어리


def test_fix_order_overflow_then_scrim_then_color():
    lay = {"textArea": "top", "scale": None, "scrim": "auto", "color": "auto"}
    s = settings()
    s1, msg = L.next_fix(L.evaluate(measure(overflow=True), s), s, lay)
    assert s1["step"] == -1 and "줄였" in msg
    s2, msg = L.next_fix(L.evaluate(measure(mean=120), s1), s1, lay)
    assert s2["scrim"] is True and "배경" in msg
    s3, msg = L.next_fix(L.evaluate(measure(mean=120), s2), s2, lay)
    assert s3["color"] == "light" and "색" in msg
    assert L.next_fix(L.evaluate(measure(mean=120), s3), s3, lay) is None  # 더 바꿀 게 없어요


def test_user_choices_are_not_overridden():
    lay = {"textArea": "top", "scale": 1, "scrim": "off", "color": "dark"}
    s = settings(step=1)
    assert L.next_fix(L.evaluate(measure(overflow=True, mean=120), s), s, lay) is None


def test_settings_from_layout():
    lay = {"textArea": "bottom", "scale": -1, "scrim": "on", "color": "auto"}
    assert L.settings_from(lay) == {"area": "bottom", "step": -1, "scrim": True, "color": None}
