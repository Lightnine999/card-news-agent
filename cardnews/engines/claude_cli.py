"""Claude CLI 엔진 (DECISIONS D2·D10).

- 인자 배열로 실행하고 셸을 거치지 않아요.
- 프로젝트마다 고정된 작업 폴더(engine/)에서 실행하고, 저장한 세션 ID로 --resume 해요.
- stream-json 이벤트에서 검색어·원문 URL을 진행 상황으로 남겨요.
- 취소되면 하위 프로세스 그룹을 끝내요.
"""

import json
import re
import subprocess
import threading
import time
from pathlib import Path

from cardnews import config, sources, support
from cardnews import proc as procs
from cardnews.proc import kill_group
from cardnews.engines import claude_prompts as prompts
from cardnews.engines import claude_schema as S
from cardnews.engines.base import Cancelled, EngineEvent, RunContext
from cardnews.errors import AppError
from cardnews.util import now

SEARCH_TOOLS = ("WebSearch", "WebFetch")
BLOCKED_TOOLS = ("Bash", "Edit", "Write", "NotebookEdit", "Task")
LIMITS = {  # (최대 턴, 제한 시간 초) [AI 기본안]
    "research": (60, 900),  # 공식 발표를 따로 찾느라 검색이 늘어요
    "deep_research": (40, 900),
    "answer": (12, 300),
    "storyboard": (12, 300),
    "svg": (4, 240),  # agy 대신 SVG 그림 그리기
    "revision": (6, 300),  # 고른 카드만 글로 고치기
}
POLL_SECONDS = 0.5
STDERR_KEEP = 4000
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{10,}|Bearer\s+[A-Za-z0-9._-]+)")
AUTH_HINTS = ("login", "log in", "api key", "authenticat", "unauthorized", "401", "oauth")


def redact(text: str) -> str:
    return SECRET.sub("[가림]", text)


def build_args(prompt: str, schema: str, session_id: str | None, step: str) -> list[str]:
    max_turns, _ = LIMITS[step]
    args = [config.claude_bin(), "-p", prompt,
            "--model", config.CLAUDE_MODEL, "--effort", config.CLAUDE_EFFORT,
            "--output-format", "stream-json", "--verbose",
            "--json-schema", schema,
            "--max-turns", str(max_turns),
            "--append-system-prompt", prompts.RULES,
            "--strict-mcp-config", "--setting-sources", "project"]
    if session_id:
        args += ["--resume", session_id]
    blocked = config.test_block_search()  # 확인용: 검색 실패 상황을 만들어요
    tools = SEARCH_TOOLS if step in ("research", "deep_research") and not blocked else ()
    if tools:
        args += ["--allowedTools", *tools]
    return [*args, "--disallowedTools", *BLOCKED_TOOLS, *(SEARCH_TOOLS if blocked else ())]


# --- 프로세스 실행 -----------------------------------------------------------------


def _progress_from(event: dict) -> list[str]:
    if event.get("type") != "assistant":
        return []
    messages = []
    for part in event.get("message", {}).get("content", []):
        if part.get("type") != "tool_use":
            continue
        args = part.get("input", {})
        if part.get("name") == "WebSearch":
            messages.append(f"검색: {str(args.get('query', ''))[:80]}")
        elif part.get("name") == "WebFetch":
            messages.append(f"원문 확인: {str(args.get('url', ''))[:100]}")
    return messages


class _Reader:
    """stdout(stream-json)과 stderr를 따로 읽어요. 원시 출력은 run 폴더에 가려서 남겨요."""

    def __init__(self, proc: subprocess.Popen, ctx: RunContext, log_path: Path):
        self.result: dict | None = None
        self.stderr = ""
        self.fetches = sources.FetchTracker()
        self._ctx = ctx
        self._threads = [
            threading.Thread(target=self._read_out, args=(proc, log_path), daemon=True),
            threading.Thread(target=self._read_err, args=(proc,), daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _read_out(self, proc, log_path: Path) -> None:
        with log_path.open("a", encoding="utf-8") as log:
            for line in proc.stdout:
                log.write(redact(line))
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    self.result = event
                self.fetches.feed(event)
                for message in _progress_from(event):
                    self._ctx.report(message)

    def _read_err(self, proc) -> None:
        for line in proc.stderr:
            if len(self.stderr) < STDERR_KEEP:
                self.stderr += redact(line)

    def join(self) -> None:
        for t in self._threads:
            t.join(timeout=5)


def run_claude(ctx: RunContext, args: list[str], step: str) -> dict:
    _, timeout = LIMITS[step]
    cwd = ctx.engine_dir or ctx.run_dir
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        proc = procs.spawn(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    except (FileNotFoundError, PermissionError) as err:
        raise AppError("TOOL_UNAVAILABLE", "Claude CLI(claude)를 실행하지 못했어요. 설치돼 있는지 확인해 주세요.",
                       {"bin": args[0]}) from err
    reader = _Reader(proc, ctx, ctx.run_dir / f"claude-{step}.jsonl")
    started = time.monotonic()
    try:
        while proc.poll() is None:
            ctx.check_cancel()
            if time.monotonic() - started > timeout:
                kill_group(proc)
                raise AppError("ENGINE_OUTPUT_INVALID", f"엔진이 {timeout // 60}분 안에 끝나지 않아서 멈췄어요.")
            time.sleep(POLL_SECONDS)
    except Cancelled:
        kill_group(proc)
        raise
    finally:
        procs.release(proc)
    reader.join()
    result = _check_result(proc.returncode, reader)
    return {**result, "_opened": sorted(reader.fetches.opened)}


def _check_result(code: int, reader: _Reader) -> dict:
    result, stderr = reader.result, reader.stderr
    if result is None or code != 0:
        raise _classify_failure(stderr or (result or {}).get("result", ""))
    if result.get("is_error") or result.get("subtype") != "success":
        if result.get("subtype") == "error_max_turns":
            raise AppError("ENGINE_OUTPUT_INVALID", "검색·확인이 너무 길어져서 멈췄어요. 다시 시도해 주세요.")
        raise _classify_failure(str(result.get("result", "")))
    denied = {d.get("tool_name") for d in result.get("permission_denials") or []}
    if denied & set(SEARCH_TOOLS):
        raise AppError("TOOL_UNAVAILABLE", "검색 도구 사용이 막혔어요.", {"denied": sorted(denied)})
    return result


def _classify_failure(text: str) -> AppError:
    lowered = text.lower()
    if "no conversation found" in lowered:
        return AppError("ENGINE_OUTPUT_INVALID", "이어갈 엔진 세션을 찾지 못했어요. 이 단계를 처음부터 다시 해 주세요.",
                        next_actions=["restart"])
    if any(hint in lowered for hint in AUTH_HINTS):
        return AppError("AUTH_REQUIRED", "Claude CLI 로그인이 필요해요. 터미널에서 claude를 실행해 로그인해 주세요.")
    first = text.strip().splitlines()[0][:200] if text.strip() else "알 수 없는 오류"
    return AppError("ENGINE_OUTPUT_INVALID", f"엔진 실행이 실패했어요: {first}")


def structured(result: dict) -> dict:
    out = result.get("structured_output")
    if isinstance(out, dict):
        return out
    try:
        parsed = json.loads(result.get("result") or "")
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        raise S.invalid("엔진이 약속한 JSON 형식으로 답하지 않았어요.")
    return parsed


# --- 엔진 ---------------------------------------------------------------------------


def _error_event(out, session_id: str | None) -> EngineEvent:
    err = out.error
    return EngineEvent(type="error", error_code=err.code if err else "SEARCH_FAILED",
                       error_message=err.message if err else "엔진이 오류를 알렸어요.",
                       session_id=session_id)


class ClaudeCliEngine:
    name = "claude-cli"

    def _call(self, ctx: RunContext, prompt: str, model, step: str):
        args = build_args(prompt, S.schema_json(model), ctx.session_id, step)
        result = run_claude(ctx, args, step)
        self.opened = result["_opened"]
        return S.parse(model, structured(result)), result.get("session_id") or ctx.session_id

    def _opened(self) -> dict:
        return {"openedUrls": self.opened}

    def start(self, ctx: RunContext, task: dict) -> EngineEvent:
        kind = task["kind"]
        if task.get("workflow") == "support" and kind in ("research", "deep_research", "storyboard"):
            return self._support(ctx, task)
        if kind == "research":
            out, sid = self._call(ctx, prompts.research(task), S.ResearchOutput, "research")
            if out.status == "error":
                return _error_event(out, sid)
            return EngineEvent(type="result", data={"candidates": S.to_candidates(out)},
                               partial=self._opened(), session_id=sid)
        if kind == "deep_research":
            return self._deep_research(ctx, task)
        if kind == "storyboard":
            out, sid = self._call(ctx, prompts.storyboard(task), S.StoryboardOutput, "storyboard")
            if out.status == "error":
                return _error_event(out, sid)
            allowed = S.allowed_urls(task["candidates"], task["researchNotes"])
            return EngineEvent(type="result", data={"cards": S.to_cards(out.cards, allowed)},
                               session_id=sid)
        return EngineEvent(type="error", error_code="TOOL_UNAVAILABLE",
                           error_message="이미지 제작은 아직 연결하지 않았어요 (구현 4~5단계).")

    def _deep_research(self, ctx: RunContext, task: dict) -> EngineEvent:
        out, sid = self._call(ctx, prompts.deep_research(task), S.DeepResearchOutput,
                              "deep_research")
        if out.status == "error":
            return _error_event(out, sid)
        selected = {c["id"] for c in task["candidates"]}
        notes = S.to_notes(out.researchNotes, selected)
        if out.status == "need_input":
            return EngineEvent(type="need_input", question=S.to_question(out.question),
                               partial={"researchNotes": notes, **self._opened()}, session_id=sid)
        allowed = S.allowed_urls(task["candidates"], notes)
        return EngineEvent(type="result", partial={"researchNotes": notes, **self._opened()},
                           session_id=sid,
                           data={"editorial": S.to_editorial(out.editorial, "ai_recommendation"),
                                 "cards": S.to_cards(out.cards, allowed)})

    def _support(self, ctx: RunContext, task: dict) -> EngineEvent:
        """지원사업·공모전 작업: 결과 형식과 지시문만 다르고, 카드는 앱 규칙으로 정리해요(support.finalize_cards)."""
        kind = task["kind"]
        if kind == "research":
            out, sid = self._call(ctx, prompts.support_research(task), S.SupportResearchOutput, "research")
            if out.status == "error":
                return _error_event(out, sid)
            return EngineEvent(type="result", data={"candidates": S.to_support_candidates(out)},
                               partial=self._opened(), session_id=sid)
        if kind == "deep_research":
            out, sid = self._call(ctx, prompts.support_deep(task), S.SupportDeepOutput, "deep_research")
            if out.status == "error":
                return _error_event(out, sid)
            notes = S.to_support_notes(out.researchNotes, {c["id"] for c in task["candidates"]})
            data = {"editorial": S.to_editorial(out.editorial, "ai_recommendation"),
                    **support_cards(out.cards, task["candidates"], notes)}
            return EngineEvent(type="result", partial={"researchNotes": notes, **self._opened()},
                               session_id=sid, data=data)
        out, sid = self._call(ctx, prompts.support_storyboard(task), S.SupportStoryboardOutput, "storyboard")
        if out.status == "error":
            return _error_event(out, sid)
        return EngineEvent(type="result", session_id=sid,
                           data=support_cards(out.cards, task["candidates"], task["researchNotes"]))

    def send_answer(self, ctx: RunContext, task: dict, question: dict,
                    answer: dict) -> EngineEvent:
        out, sid = self._call(ctx, prompts.answer(task, question, answer), S.AnswerOutput,
                              "answer")
        if out.status == "error":
            return _error_event(out, sid)
        allowed = S.allowed_urls(task["candidates"], task["researchNotes"])
        return EngineEvent(type="result", session_id=sid,
                           data={"editorial": S.to_editorial(out.editorial, "user_answer"),
                                 "cards": S.to_cards(out.cards, allowed)})


def support_cards(cards, candidates: list[dict], notes: list[dict]) -> dict:
    """엔진 카드 → 앱 카드: 조사에 없던 URL을 빼고, 확인 결과로 거르고 순서·문구를 정해요."""
    allowed = S.allowed_urls(candidates, notes)
    raw = S.to_cards(cards, allowed, (support.CARD_RANGE[0], S.MAX_CANDIDATES + 2))
    final, dropped = support.finalize_cards(raw, notes, candidates, now().date())
    return {"cards": final, "dropped": dropped}
