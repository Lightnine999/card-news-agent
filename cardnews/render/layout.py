"""글자 점검 판정과 자동 고침 규칙 (설계: docs/2026-10-23-text-render-design.md).

브라우저가 잰 값(measure)을 받아 판정만 해요. 브라우저를 띄우지 않아서 규칙을 따로 시험할 수 있어요.
  measure = {"blocks": [{"name", "rect", "fontPx", "bgMean", "bgStd"}], "overflow": bool, "size": [w, h]}
  settings = {"area": top|center|bottom, "step": 정수, "scrim": bool, "color": dark|light|None}
"""

CARD_SIZE = [1080, 1350]
MIN_FONT_PX = 32
MIN_CONTRAST = 4.5
BUSY_STD = 28  # 글자 자리 배경의 밝기 표준편차가 이 이상이면 물건과 겹친 것으로 봐요 [AI 기본안]
MIN_STEP = -3
TEXT_GRAY = {"dark": 0x15, "light": 0xF2}  # #151515, #f4f2ee의 밝기
DARK_BACKGROUND = 128  # 배경 평균 밝기가 이보다 낮으면 밝은 글자로 시작해요


def _linear(gray: float) -> float:
    c = gray / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(gray_a: float, gray_b: float) -> float:
    """두 회색 밝기(0~255)의 WCAG 대비."""
    hi, lo = sorted((_linear(gray_a), _linear(gray_b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pick_color(mean_gray: float) -> str:
    return "light" if mean_gray < DARK_BACKGROUND else "dark"


def settings_from(layout: dict) -> dict:
    """사용자 조정 값(auto 포함)을 첫 렌더링 설정으로 바꿔요. 글자 색이 auto면 배경을 잰 뒤 정해요."""
    color = layout.get("color", "auto")
    return {"area": layout["textArea"], "step": layout.get("scale") or 0,
            "scrim": layout.get("scrim") == "on", "color": None if color == "auto" else color}


def _block_problems(block: dict, color: str) -> list[str]:
    problems = []
    if block["fontPx"] < MIN_FONT_PX:
        problems.append("small")
    if contrast_ratio(TEXT_GRAY[color], block["bgMean"]) < MIN_CONTRAST:
        problems.append("contrast")
    if block["bgStd"] >= BUSY_STD:
        problems.append("busy")
    return problems


def evaluate(measure: dict, settings: dict) -> dict:
    """가독성 점검 결과 (API_SPEC 2.5 checks.layout)."""
    color = settings["color"] or "dark"
    blocks = [{"name": b["name"], "rect": b["rect"], "problems": _block_problems(b, color)}
              for b in measure["blocks"]]
    min_font = min((b["fontPx"] for b in measure["blocks"]), default=0)
    contrast = min((contrast_ratio(TEXT_GRAY[color], b["bgMean"]) for b in measure["blocks"]), default=0)
    busy = max((b["bgStd"] for b in measure["blocks"]), default=0)
    fails, warns = [], []
    if measure["overflow"]:
        fails.append("잘림: 글자가 정해진 자리를 넘쳐요. 크기를 줄이거나 문구를 줄여 주세요.")
    if min_font < MIN_FONT_PX:
        fails.append(f"글자 크기: 가장 작은 글자가 {min_font:.0f}px이에요(기준 {MIN_FONT_PX}px).")
    if contrast < MIN_CONTRAST:
        fails.append(f"대비: 글자와 배경 대비가 {contrast:.1f}:1이에요(기준 {MIN_CONTRAST}:1).")
    if measure["size"] != CARD_SIZE:
        fails.append(f"크기: 결과가 {measure['size'][0]}×{measure['size'][1]}이에요(기준 1080×1350).")
    if busy >= BUSY_STD:
        warns.append("겹침: 글자가 그림 속 물건과 겹쳐 보여요. 위치를 옮기거나 글자 뒤 배경을 켜 보세요.")
    status = "fail" if fails else "warn" if warns else "pass"
    return {"status": status, "overflow": measure["overflow"], "minFontPx": round(min_font, 1),
            "contrastRatio": round(contrast, 2), "busy": round(busy, 1), "size": measure["size"],
            "items": fails + warns, "blocks": blocks}


def next_fix(checks: dict, settings: dict, layout: dict) -> tuple[dict, str] | None:
    """점검에 걸린 것을 하나만 고친 설정과 안내 문구. 고칠 게 없거나 사용자가 정한 항목뿐이면 None."""
    contrast_bad = checks["contrastRatio"] < MIN_CONTRAST
    if checks["overflow"] and layout.get("scale") is None and settings["step"] > MIN_STEP:
        return {**settings, "step": settings["step"] - 1}, "넘쳐서 글자를 한 단계 줄였어요"
    if (contrast_bad or checks["busy"] >= BUSY_STD) and layout.get("scrim", "auto") == "auto" \
            and not settings["scrim"]:
        return {**settings, "scrim": True}, "글자 뒤에 옅은 배경을 깔았어요"
    if contrast_bad and layout.get("color", "auto") == "auto" and not settings.get("flipped"):
        flipped = "light" if (settings["color"] or "dark") == "dark" else "dark"
        return {**settings, "color": flipped, "flipped": True}, "대비가 부족해서 글자 색을 바꿨어요"
    return None
