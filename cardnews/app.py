"""웹 API와 화면 파일 (API_SPEC 3). 오래 걸리는 일은 run으로 넘기고 바로 답해요."""

import re
import shutil
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from cardnews import config, db, repo, service, views
from cardnews.images import files as image_files
from cardnews.errors import AppError

STATIC = config.ROOT / "static"
REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


def request_id(**extra):
    return Field(min_length=8, max_length=64, pattern=REQUEST_ID_PATTERN, **extra)

app = FastAPI(title="카드뉴스 에이전트", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def _revalidate_screen_files(request: Request, call_next):
    # 앱을 고친 뒤에도 브라우저가 예전 화면 파일을 쓰지 않게, 매번 새 버전이 있는지 확인하게 해요
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith(("/static/", "/p/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --- 오류 응답 (API_SPEC 0.4) ---------------------------------------------------


@app.exception_handler(AppError)
async def _app_error(_: Request, err: AppError):
    return JSONResponse({"error": err.to_dict()}, status_code=err.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, err: RequestValidationError):
    fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
              for e in err.errors()]
    body = AppError("VALIDATION_ERROR", "입력 형식이 올바르지 않아요.", {"fields": fields})
    return JSONResponse({"error": body.to_dict()}, status_code=422)


# --- 요청 본문 -------------------------------------------------------------------


class CreateProject(BaseModel):
    topic: str
    periodDays: Literal[7, 30] = 7
    requestId: str | None = request_id(default=None)

    @field_validator("topic")
    @classmethod
    def _topic(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("주제는 1~100자예요.")
        return value


class StartResearch(BaseModel):
    requestId: str = request_id()
    periodDays: Literal[7, 30] = 7


class Selection(BaseModel):
    candidateIds: list[str] = Field(max_length=20)
    version: int


class Versioned(BaseModel):
    version: int
    requestId: str = request_id()


class AnswerValue(BaseModel):
    optionId: str | None = None
    optionIds: list[str] | None = None
    freeText: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _exactly_one(self):
        if sum(v is not None for v in (self.optionId, self.optionIds, self.freeText)) != 1:
            raise ValueError("optionId·optionIds·freeText 중 하나만 보내 주세요.")
        return self

    def as_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class SubmitAnswer(BaseModel):
    questionId: str
    version: int
    answer: AnswerValue
    requestId: str = request_id()


class StoryboardFeedback(Versioned):
    instruction: str = Field(min_length=1, max_length=500)


class Approve(Versioned):
    stage: Literal["storyboard", "final"]


class RetryCard(BaseModel):
    resultVersion: int
    requestId: str = request_id()


class LayoutChange(BaseModel):
    """바꿀 항목만 보내요. 보내지 않은 항목은 그대로예요 (설계: 직접 조정)."""
    textArea: Literal["top", "center", "bottom"] | None = None
    scale: Literal["auto", -2, -1, 0, 1, 2] | None = None
    scrim: Literal["auto", "on", "off"] | None = None
    color: Literal["auto", "dark", "light"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=30)
    keyLine: str | None = Field(default=None, min_length=1, max_length=60)
    body: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("title", "keyLine", "body")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("빈 문구는 보낼 수 없어요.")  # 공백만 보내면 카드에서 글자가 사라져요
        return value.strip() if value is not None else value


class CardLayout(BaseModel):
    resultVersion: int
    layout: LayoutChange
    requestId: str = request_id()


class Resume(BaseModel):
    mode: Literal["continue", "restart"]
    requestId: str = request_id()


def _respond(result: tuple[int, dict]) -> JSONResponse:
    status_code, body = result
    return JSONResponse(body, status_code=status_code)


def _body(model: BaseModel) -> dict:
    return model.model_dump(exclude={"requestId"}, mode="json")


# --- 화면 ------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
@app.get("/p/{project_id}", include_in_schema=False)
async def index(project_id: str | None = None):
    return FileResponse(STATIC / "index.html")


# --- 프로젝트 --------------------------------------------------------------------


@app.get("/api/projects")
def list_projects():
    with db.transaction() as conn:
        return {"projects": [views.project_summary(conn, p) for p in repo.list_projects(conn)]}


@app.post("/api/projects")
def create_project(req: CreateProject):
    def action(conn):
        return 201, {"projectId": service.create_project(conn, req.topic)["id"]}

    return _respond(service.idempotent("_global", req.requestId, "POST /api/projects",
                                       _body(req), action))


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    with db.transaction() as conn:
        return views.project_view(conn, repo.get_project(conn, project_id))


@app.post("/api/projects/{project_id}/research")
def start_research(project_id: str, req: StartResearch):
    def action(conn):
        return 202, service.start_research(conn, project_id, req.periodDays)

    return _respond(service.idempotent(project_id, req.requestId, "research", _body(req), action))


@app.post("/api/projects/{project_id}/selection")
def save_selection(project_id: str, req: Selection):
    with db.transaction() as conn:
        return service.save_selection(conn, project_id, req.candidateIds, req.version)


@app.post("/api/projects/{project_id}/deep-research")
def start_deep_research(project_id: str, req: Versioned):
    def action(conn):
        return 202, service.start_deep_research(conn, project_id, req.version)

    return _respond(service.idempotent(project_id, req.requestId, "deep-research",
                                       _body(req), action))


@app.post("/api/projects/{project_id}/answers")
def submit_answer(project_id: str, req: SubmitAnswer):
    def action(conn):
        return 202, service.submit_answer(conn, project_id, req.questionId, req.version,
                                          req.answer.as_dict())

    return _respond(service.idempotent(project_id, req.requestId, "answers", _body(req), action))


@app.post("/api/projects/{project_id}/storyboard/feedback")
def storyboard_feedback(project_id: str, req: StoryboardFeedback):
    def action(conn):
        return 202, service.storyboard_feedback(conn, project_id, req.instruction, req.version)

    return _respond(service.idempotent(project_id, req.requestId, "storyboard-feedback",
                                       _body(req), action))


@app.post("/api/projects/{project_id}/approve")
def approve(project_id: str, req: Approve):
    def action(conn):
        return service.approve(conn, project_id, req.stage, req.version)

    return _respond(service.idempotent(project_id, req.requestId, "approve", _body(req), action))


@app.post("/api/projects/{project_id}/cards/{card_id}/retry")
def retry_card(project_id: str, card_id: str, req: RetryCard):
    def action(conn):
        return 202, service.retry_card(conn, project_id, card_id, req.resultVersion)

    return _respond(service.idempotent(project_id, req.requestId, f"retry:{card_id}",
                                       _body(req), action))


@app.post("/api/projects/{project_id}/cards/{card_id}/layout")
def card_layout(project_id: str, card_id: str, req: CardLayout):
    change = req.layout.model_dump(exclude_none=True)

    def action(conn):
        return 202, service.update_layout(conn, project_id, card_id, req.resultVersion, change)

    return _respond(service.idempotent(project_id, req.requestId, f"layout:{card_id}",
                                       _body(req), action))


@app.post("/api/projects/{project_id}/render")
def render_pending(project_id: str, req: RetryCard):
    def action(conn):
        return 202, service.render_pending(conn, project_id, req.resultVersion)

    return _respond(service.idempotent(project_id, req.requestId, "render", _body(req), action))


PROJECT_ID = re.compile(r"^prj_[0-9a-f]{12}$")


@app.get("/api/projects/{project_id}/files/{path:path}")
def project_file(project_id: str, path: str):
    """프로젝트 폴더 안의 그림 파일만 내줘요. 폴더 밖·링크·그림이 아닌 파일은 없는 것으로 답해요."""
    missing = AppError("NOT_FOUND", "파일을 찾지 못했어요.")
    if not PROJECT_ID.match(project_id):
        raise missing
    base = (config.data_dir() / "projects" / project_id).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file() or (base / path).is_symlink():
        raise missing
    media = image_files.content_type(target)
    if media is None:
        raise missing
    # SVG를 주소로 직접 열어도 그 안의 스크립트·외부 요청이 실행되지 않게 막아요
    headers = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
               "X-Content-Type-Options": "nosniff"}
    return FileResponse(target, media_type=media, headers=headers)


# --- 작업 ------------------------------------------------------------------------


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    with db.transaction() as conn:
        return service.cancel_run(conn, run_id)


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str, req: Resume):
    with db.transaction() as conn:
        project_id = repo.get_run(conn, run_id)["projectId"]

    def action(conn):
        return 202, service.resume_run(conn, run_id, req.mode)

    return _respond(service.idempotent(project_id, req.requestId, f"resume:{run_id}",
                                       _body(req), action))


# --- 상태 점검 -------------------------------------------------------------------


def _chromium_installed() -> bool:
    """Playwright가 받은 Chromium이 있는지만 봐요(실행은 실제 렌더링에서 확인해요)."""
    import os
    from pathlib import Path
    default = Path.home() / "Library" / "Caches" / "ms-playwright"
    folder = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", default))
    return folder.is_dir() and any(folder.glob("chromium*"))


@app.get("/api/health")
def health():
    font_dir = config.ROOT / "static" / "fonts"
    return {
        "engine": config.engine_name(),
        "claude": shutil.which("claude") is not None,
        "agy": shutil.which("agy") is not None,
        "chromium": _chromium_installed(),
        "font": any(font_dir.glob("Pretendard*")) if font_dir.exists() else False,
        "login": "unknown",  # 로그인 여부는 실제 호출에서만 알 수 있어요
    }
