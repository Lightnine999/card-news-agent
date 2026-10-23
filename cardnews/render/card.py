"""카드 한 장 렌더링: HTML 만들기 → 재기 → 자동 고침(최대 3번) → PNG 저장 → 크기 다시 확인."""

from pathlib import Path

from cardnews.render import chromium, html, layout as rules

MAX_FIXES = 3


def _finish_color(page, settings: dict, measured: dict) -> dict:
    """글자 색이 auto면 글자 자리 배경 밝기로 정해요."""
    if settings["color"]:
        return settings
    means = [b["bgMean"] for b in measured["blocks"]] or [255]
    chosen = {**settings, "color": rules.pick_color(sum(means) / len(means))}
    chromium.apply(page, chosen)
    return chosen


def render_card(browser, *, out_stem: Path, texts: dict, role: str, layout: dict,
                bg: Path | None, disclose: bool) -> dict:
    """out_stem.html·out_stem.png를 만들고 점검 결과를 돌려줘요."""
    settings = rules.settings_from(layout)
    html_path, png_path = out_stem.with_name(out_stem.name + ".html"), out_stem.with_name(out_stem.name + ".png")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    bg_url = bg.as_uri() if bg else None
    html_path.write_text(html.build_html(texts, settings, bg_url, role, disclose), encoding="utf-8")
    page = browser.open(html_path)
    fixes: list[str] = []
    try:
        chromium.apply(page, settings)
        settings = _finish_color(page, settings, chromium.measure(page))
        while True:
            checks = rules.evaluate(chromium.measure(page), settings)
            fix = rules.next_fix(checks, settings, layout)
            if fix is None or len(fixes) >= MAX_FIXES:
                break
            settings, message = fix
            fixes.append(message)
            chromium.apply(page, settings)
        size = chromium.capture(page, png_path)
    finally:
        page.close()
    applied = {k: v for k, v in settings.items() if k != "flipped"}
    if size != rules.CARD_SIZE:
        checks = {**checks, "status": "fail", "size": size,
                  "items": [*checks["items"], f"크기: 결과가 {size[0]}×{size[1]}이에요(기준 1080×1350)."]}
    html_path.write_text(html.build_html(texts, applied, bg_url, role, disclose), encoding="utf-8")
    return {"png": png_path, "checks": checks, "applied": applied, "autoFixes": fixes}
