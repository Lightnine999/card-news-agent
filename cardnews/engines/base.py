"""공통 엔진 인터페이스 (API_SPEC 4.2).

엔진 결과는 progress / need_input / result / error 네 가지로 정규화해요.
이 규약은 이 앱이 정한 것이고, 각 CLI에 내장된 공통 규격이 아니에요.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Protocol

EventType = Literal["need_input", "result", "error"]


class Cancelled(Exception):
    """사용자가 작업을 취소했어요. 엔진은 하던 일을 멈추고 이 예외를 올려요."""


@dataclass(frozen=True)
class EngineEvent:
    type: EventType
    data: dict = field(default_factory=dict)       # result: 단계별 결과
    question: dict | None = None                   # need_input: 질문 (id·prompt·options…)
    partial: dict = field(default_factory=dict)    # need_input: 질문 전까지 나온 결과
    error_code: str | None = None
    error_message: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class RunContext:
    run_id: str
    project_id: str
    topic: str
    session_id: str | None
    run_dir: Path
    report: Callable[[str], None]          # 진행 메시지 남기기 (progress)
    check_cancel: Callable[[], None]       # 취소됐으면 Cancelled를 올려요
    engine_dir: Path | None = None         # 프로젝트마다 고정된 엔진 작업 폴더


class Engine(Protocol):
    name: str

    def start(self, ctx: RunContext, task: dict) -> EngineEvent: ...

    def send_answer(self, ctx: RunContext, task: dict, question: dict,
                    answer: dict) -> EngineEvent: ...


def get_engine(name: str) -> Engine:
    if name == "mock":
        from cardnews.engines.mock import MockEngine

        return MockEngine()
    if name == "claude-cli":
        from cardnews.engines.claude_cli import ClaudeCliEngine

        return ClaudeCliEngine()
    from cardnews.errors import AppError

    raise AppError("TOOL_UNAVAILABLE", f"'{name}' 엔진은 아직 연결하지 않았어요.",
                   {"engine": name})
