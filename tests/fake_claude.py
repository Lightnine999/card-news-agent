"""테스트용 가짜 `claude`. 실제 CLI의 stream-json 출력 모양을 흉내 내요.

받은 인자를 FAKE_CLAUDE_LOG에 한 줄씩 남겨서, 테스트가 --resume·인자 배열을 확인해요.
FAKE_CLAUDE_SCENARIO로 실패 상황을 고를 수 있어요.
"""

import json
import os
import sys
import time
from datetime import date, timedelta

SESSION = "11111111-2222-3333-4444-555555555555"


def emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def candidate(n: int, url: str, date: str | None) -> dict:
    return {
        "title": f"후보 {n}", "summary": "요약", "category": "모델",
        "publishedAt": date, "eventDate": None, "sources": [
            {"url": url, "name": f"출처 {n}", "type": "official"}],
        "whyPick": "이유", "uncertainty": "불확실", "status": "released",
    }


def requested_date(prompt: str) -> date:
    """지시문의 "조사 기준 시각:" 줄에서 날짜를 읽어요. 테스트가 실행 날짜에 묶이지 않게요."""
    line = next(l for l in prompt.splitlines() if l.startswith("조사 기준 시각:"))
    return date.fromisoformat(line.split(":", 1)[1].strip()[:10])


def research(count: int, prompt: str, scenario: str) -> dict:
    day = requested_date(prompt)
    recent = (day - timedelta(days=2)).isoformat()
    cands = [candidate(i, f"https://news.example.com/{i}", recent) for i in range(1, count + 1)]
    if scenario == "out_of_period":
        cands.append(candidate(90, "https://news.example.com/old", (day - timedelta(days=20)).isoformat()))
        cands.append(candidate(91, "https://news.example.com/future", (day + timedelta(days=3)).isoformat()))
    if cands:
        cands[0] = {**cands[0], "publishedAt": "어제"}                      # 잘못된 날짜
        cands[-1] = {**cands[-1], "sources": [{"url": "javascript:alert(1)", "name": "x",
                                               "type": "blog"}, *cands[-1]["sources"]]}
    return {"status": "result", "candidates": cands}


def deep(prompt: str) -> dict:
    ids = [line.split("id=")[1].split()[0] for line in prompt.splitlines() if "id=" in line]
    notes = [{"candidateId": cid, "facts": [{"text": "사실", "sourceUrls": ["https://news.example.com/1"]}],
              "limits": [], "conflicts": [], "primarySources": ["https://news.example.com/1"],
              "unreachable": []} for cid in ids]
    return {"status": "need_input", "researchNotes": notes, "question": {
        "id": "q_audience", "prompt": "어떤 독자에게 전달할까요?",
        "options": [{"id": "dev", "label": "개발자", "description": "도구 중심"},
                    {"id": "general", "label": "일반 사용자", "description": "쉬운 설명"}],
        "allowFreeText": True, "recommendedOptionId": "dev", "recommendationReason": "개발 소식이라서"}}


def cards() -> list[dict]:
    roles = ["cover", "body", "body", "body", "summary"]
    return [{"role": r, "title": f"카드 {i}", "keyLine": "핵심", "body": f"카드 {i} 본문 문장이에요.",
             "imageRole": "분위기 잡기",
             "sourceUrls": ["https://news.example.com/1", "https://made-up.example.com/x"],
             "imagePlan": {"kind": "generated", "prompt": "배경", "textArea": "top"}}
            for i, r in enumerate(roles, 1)]


def answer_result() -> dict:
    return {"status": "result", "editorial": {
        "audience": "개발자", "whyUseful": "유용", "format": "핵심 요약형",
        "hooks": ["후킹 1", "후킹 2"], "decidedBy": "user_answer"}, "cards": cards()}


def fetch(tid: str, url: str, code: int, final: str | None = None) -> None:
    """실제 CLI처럼 WebFetch 요청(assistant)과 결과(user, tool_use_result.code)를 내보내요."""
    emit({"type": "assistant", "session_id": SESSION, "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "WebFetch", "input": {"url": url}}]}})
    emit({"type": "user", "session_id": SESSION, "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "본문"}]},
        "tool_use_result": {"code": code, "codeText": "", "url": final or url}})


def support_candidate(n: int, url_type: str = "official", status: str = "confirmed", deadline=None) -> dict:
    return {"title": f"공고 {n}", "summary": "요약", "kind": "공모전", "host": "주최", "hostType": "gov",
            "target": "대학생", "amountText": f"상금 {n}천만 원", "amountKRW": n * 10_000_000,
            "dateStatus": status, "deadline": deadline, "deadlineTime": None, "rollingText": None,
            "openMonth": None, "basis": "", "whyPick": "이유", "uncertainty": "불확실",
            "sources": [{"url": f"https://gov.example.go.kr/notice/{n}", "name": f"공고 {n}", "type": url_type}]}


def support_research(prompt: str) -> dict:
    soon = (requested_date(prompt) + timedelta(days=10)).isoformat()
    cands = [support_candidate(n, deadline=soon) for n in range(1, 5)]
    blog = {**support_candidate(9, "blog", deadline=soon), "title": "모음 사이트에만 있는 공고"}
    return {"status": "result", "candidates": [*cands, blog]}


def support_deep(prompt: str) -> dict:
    ids = [line.split("id=")[1].split()[0] for line in prompt.splitlines() if line.startswith("- id=")]
    soon = (date.today() + timedelta(days=10)).isoformat()
    notes = [{"candidateId": cid, "facts": [], "limits": [], "conflicts": [],
              "primarySources": [f"https://gov.example.go.kr/notice/{cid[5:]}"], "unreachable": [],
              "notice": {"target": "대학생", "applyVia": "주최", "amountText": "상금 1천만 원", "amountKRW": 10_000_000,
                         "dateStatus": "confirmed", "deadline": soon, "deadlineTime": None, "rollingText": None,
                         "openMonth": None, "basis": "", "officialUrl": f"https://gov.example.go.kr/notice/{cid[5:]}",
                         "prepare": "포트폴리오"}} for cid in ids]
    plan = {"kind": "generated", "prompt": "배경", "textArea": "top"}
    card = lambda role, cid: {"role": role, "title": "t", "keyLine": "k", "body": "엔진이 쓴 D-1", "imageRole": "r",  # noqa: E731
                              "sourceUrls": [], "imagePlan": plan, "candidateId": cid}
    cards = [card("cover", None), *[card("body", cid) for cid in ids], card("summary", None)]
    editorial = {"audience": "대학생·예비 창업자", "whyUseful": "유용", "format": "공고 카드형", "hooks": ["h"],
                 "decidedBy": "ai_recommendation"}
    return {"status": "result", "researchNotes": notes, "editorial": editorial, "cards": cards}


def main() -> None:
    args = sys.argv[1:]
    with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": args, "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
    scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "ok")
    prompt = args[args.index("-p") + 1]
    schema = json.loads(args[args.index("--json-schema") + 1])
    kind = schema["title"]

    if scenario == "auth":
        print("Invalid API key · Please run /login", file=sys.stderr)
        sys.exit(1)
    if "--resume" in args and scenario == "lost_session":
        print(f"No conversation found with session ID: {args[args.index('--resume') + 1]}",
              file=sys.stderr)
        sys.exit(1)
    if scenario == "slow":
        with open(os.environ["FAKE_CLAUDE_PID"], "w") as f:
            f.write(str(os.getpid()))
        time.sleep(60)

    emit({"type": "system", "subtype": "init", "session_id": SESSION, "mcp_servers": []})
    emit({"type": "assistant", "session_id": SESSION, "message": {"content": [
        {"type": "tool_use", "name": "WebSearch", "input": {"query": "AI 뉴스 이번 주"}}]}})

    if scenario == "bad_output":
        emit({"type": "result", "subtype": "success", "is_error": False, "session_id": SESSION,
              "result": "형식 없는 글", "structured_output": None, "permission_denials": []})
        return
    if kind == "SvgImageOutput":
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350">'
               '<rect width="1080" height="1350" fill="#102040"/><circle cx="540" cy="1000" r="200" fill="#187882"/>'
               '<path d="M0 1200 L1080 900 L1080 1350 Z" fill="#264653"/><text x="40" y="80">글자</text>'
               '<script>alert(1)</script></svg>')
        out = {"svg": "그림을 그리지 못했어요" if scenario == "svg_bad" else svg}
    elif kind == "SupportResearchOutput":
        out = support_research(prompt)
    elif kind == "SupportDeepOutput":
        out = support_deep(prompt)
    elif kind == "ResearchOutput":
        fetch("f1", "https://www.news.example.com/1/", 200)   # 주소 모양이 달라도 같은 페이지
        fetch("f2", "https://news.example.com/2", 403)        # 막힌 페이지는 연 것이 아니에요
        out = research(3 if scenario == "few" else 8, prompt, scenario)
    elif kind == "DeepResearchOutput":
        fetch("f3", "https://news.example.com/3", 200)
        out = deep(prompt)
    else:  # AnswerOutput / StoryboardOutput
        out = answer_result()
    emit({"type": "result", "subtype": "success", "is_error": False, "session_id": SESSION,
          "result": json.dumps(out, ensure_ascii=False), "structured_output": out,
          "permission_denials": []})


if __name__ == "__main__":
    main()
