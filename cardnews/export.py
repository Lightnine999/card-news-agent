"""최종 승인한 버전 내보내기: 카드 PNG, sources.md, image-credits.md, ZIP (API_SPEC 3 · 14).

exports/v<결과 버전>/ 에 만들고, ZIP을 다시 열어 검사(verify_export)한 결과를 함께 남겨요.
"""

import json
import shutil
import zipfile
from pathlib import Path

from cardnews import config, db, pipeline, repo, sources
from cardnews.engines.base import RunContext
from cardnews.util import now_iso
from cardnews import verify_export

ROLE = {"cover": "표지", "body": "본문", "summary": "요약", "next_action": "다음 행동"}
TYPE = {"official": "공식", "paper": "논문", "press": "언론", "blog": "블로그", "unknown": "미분류"}


def card_file(order: int) -> str:
    return f"cards/card_{order:02d}.png"


def source_index(data: dict) -> dict[str, dict]:
    """정규화한 URL → 출처 정보(이름·종류·게시일·후보 제목·엔진이 열어 봤는지)."""
    research = data.get("research") or {}
    marked = sources.mark(research.get("candidates", []), data.get("openedUrls", []))
    index = {}
    for cand in marked:
        for src in cand["sources"]:
            index.setdefault(sources.normalize(src["url"]), {
                "url": src["url"], "name": src.get("name") or src["url"], "type": src.get("type", "unknown"),
                "publishedAt": cand.get("publishedAt"), "eventDate": cand.get("eventDate"),
                "candidate": cand["title"], "candidateId": cand["id"], "opened": src["opened"]})
    titles = {c["id"]: c["title"] for c in research.get("candidates", [])}
    opened_all = {sources.normalize(u) for u in data.get("openedUrls", [])}
    for note in data.get("researchNotes") or []:  # 심층 조사에서 따로 찾은 공식 자료
        dated = sources.normalize(note["officialDateSource"]) if note.get("officialDateSource") else None
        for url in note.get("primarySources", []):
            key = sources.normalize(url)
            if key not in index:
                # 그 1차 자료에서 확인한 공식 발표일을 게시일로 써요 (없으면 미확인)
                index[key] = {"url": url, "name": url, "type": "official",
                              "publishedAt": note.get("officialDate") if key == dated else None,
                              "eventDate": None, "candidate": titles.get(note.get("candidateId")),
                              "candidateId": note.get("candidateId"), "opened": key in opened_all}
    return index


def _texts(plan: dict, card: dict) -> dict:
    layout = card.get("layout") or {}
    return {k: layout.get(k) if layout.get(k) is not None else plan.get(k) for k in ("title", "keyLine", "body")}


def sources_md(project: dict, version: int) -> str:
    data = project["data"]
    research = data["research"]
    index = source_index(data)
    cards = {c["cardId"]: c for c in data["result"]["cards"]}
    lines = [f"# 출처 기록 — {project['topic']}", "",
             f"- 조사 기준 시각: {research['requestedAt']}",
             f"- 조사 기간: 최근 {research['period']['days']}일 ({research['period']['from'][:10]} ~ {research['period']['to'][:10]})",
             f"- 결과 버전: v{version} · 최종 승인: {data['finalApproval']['approvedAt']}",
             "- '엔진이 열어 봄'은 조사 엔진이 그 주소를 실제로 열어 내용을 받았다는 뜻이에요. 지금도 열리는지는 확인하지 않았어요.", ""]
    for plan in data["storyboard"]["cards"]:
        card = cards[plan["id"]]
        texts = _texts(plan, card)
        edited = (card.get("layout") or {}).get("textEdited")
        lines += [f"## 카드 {plan['order']}. {texts['title']} ({ROLE.get(plan['role'], plan['role'])})",
                  f"- 파일: {card_file(plan['order'])}",
                  f"- 핵심 문장: {texts['keyLine']}"]
        if texts.get("body") and plan["role"] != "cover":
            lines.append(f"- 본문: {texts['body']}")
        lines.append(f"- 문구: {'스토리보드에서 고쳤어요 (' + card['revisionNote'] + ')' if card.get('revisionNote') else '스토리보드에서 고쳤어요' if edited else '스토리보드 그대로'}")
        urls = plan.get("sourceUrls", [])
        if not urls:
            lines.append("- 근거: 없음")
        for url in urls:
            info = index.get(sources.normalize(url))
            if info is None:
                lines.append(f"- 근거: {url} — 조사 기록에 없는 주소")
                continue
            lines.append(f"- 근거: [{info['name']}]({url}) — {TYPE.get(info['type'], info['type'])}, "
                         f"게시일 {info['publishedAt'] or '미확인'}, "
                         f"{'엔진이 열어 봄' if info['opened'] else '엔진이 열어 보지 않음'}")
        lines.append("")
    return "\n".join(lines)


def credits_md(project: dict, version: int) -> str:
    data = project["data"]
    cards = {c["cardId"]: c for c in data["result"]["cards"]}
    lines = [f"# 이미지 사용 기록 — {project['topic']}", "", f"- 결과 버전: v{version}",
             "- 배경 그림은 모두 생성 이미지예요. 실제 제품 화면이나 사건 사진이 아니에요. 생성 이미지라고 해서 저작권 문제가 없다고 단정하지 않아요.",
             "- 카드 안 글자는 그림에 그려 넣지 않고 앱이 따로 올렸어요(Pretendard, SIL OFL 1.1).", ""]
    for plan in data["storyboard"]["cards"]:
        card = cards[plan["id"]]
        img = card.get("image") or {}
        conv = img.get("conversationId")
        lines += [f"## 카드 {plan['order']} ({card_file(plan['order'])})",
                  f"- 출처 종류: {'생성 이미지' if str(img.get('origin', '')).startswith('generated') else img.get('origin', '없음')}",
                  f"- 도구: {img.get('tool', '—')}",
                  f"- 만든 시각: {img.get('createdAt', '—')}",
                  f"- 원본 형식·크기: {img.get('originalFormat', '—')} {'×'.join(map(str, img.get('originalSize') or []))}"]
        if conv:
            lines.append(f"- agy 대화 ID(앞 8자리): {conv[:8]}")
        if img.get("fallbackFrom"):
            lines.append(f"- agy로 못 만들어 Claude CLI가 SVG로 대신 그렸어요: {img['fallbackFrom'].get('message', '')}")
        mark = '오른쪽 아래 "AI 생성 이미지"' if img else "없음"
        lines.append(f"- 카드 안 표기: {mark}")
        prompt = (img.get("prompt") or "—").strip().splitlines()
        lines += ["- 요청 문장:", "", *[f"    {line}" for line in prompt], ""]  # 들여쓰기 블록이라 프롬프트 안 ```에도 안 깨져요
    return "\n".join(lines)


def build(project: dict, version: int) -> tuple[Path, list[dict]]:
    """내보내기 폴더와 ZIP을 만들고 (폴더, 파일 목록)을 돌려줘요."""
    project_dir = config.data_dir() / "projects" / project["id"]
    out = project_dir / "exports" / f"v{version}"
    if out.exists():
        shutil.rmtree(out)
    (out / "cards").mkdir(parents=True)
    cards = {c["cardId"]: c for c in project["data"]["result"]["cards"]}
    for plan in project["data"]["storyboard"]["cards"]:
        png = cards[plan["id"]].get("png")
        if png:  # 없으면 검사에서 '누락'으로 잡아요
            shutil.copy2(project_dir / png, out / card_file(plan["order"]))
    (out / "sources.md").write_text(sources_md(project, version), encoding="utf-8")
    (out / "image-credits.md").write_text(credits_md(project, version), encoding="utf-8")
    zip_name = f"cardnews_{project['id']}_v{version}.zip"
    members = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    with zipfile.ZipFile(out / zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in members:
            zf.write(out / name, name)
    listed = [*members, zip_name]
    return out, [{"name": n, "bytes": (out / n).stat().st_size} for n in listed]


def execute(run: dict, project: dict, ctx: RunContext) -> None:
    version = run["payload"]["resultVersion"]
    ctx.report(f"v{version} 내보내기 파일 만드는 중")
    out, listed = build(project, version)
    ctx.report("ZIP을 다시 열어 누락·잘림·출처·날짜 확인 중")
    report = verify_export.verify(project, out, out / listed[-1]["name"])
    (out / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "verify.md").write_text(verify_export.to_markdown(report), encoding="utf-8")
    zip_path = out / listed[-1]["name"]
    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:  # 검사 결과도 ZIP에 넣어요(검사 뒤라 검사 대상은 아니에요)
        zf.write(out / "verify.md", "verify.md")
    listed = [{"name": f["name"], "bytes": (out / f["name"]).stat().st_size} for f in listed]
    listed += [{"name": n, "bytes": (out / n).stat().st_size} for n in ("verify.md", "verify.json")]
    exports = {"resultVersion": version, "createdAt": now_iso(), "files": listed,
               "verify": report["summary"] | {"items": report["items"]}}
    with db.transaction() as conn:
        if repo.get_run(conn, run["id"])["cancelRequested"]:
            return
        current = repo.get_project(conn, project["id"])
        repo.save_project(conn, {**current, "data": {**current["data"], "exports": exports}})
        pipeline.finish_run(conn, run["id"], "succeeded")

