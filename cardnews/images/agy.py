"""Antigravity CLI(agy)로 카드 배경 그림 만들기 (DECISIONS D9·D11).

- agy에는 자연어로 요청하고, 확인하지 않은 하위 명령(`agy image generate` 등)은 쓰지 않아요.
- agy는 그림을 자기 폴더(brain/<conversation_id>/)에만 저장해요. 응답 JSON의 status=SUCCESS나
  "진행 중" 같은 글은 믿지 않고, 그 폴더에 호출 이후 새로 생긴 그림 파일로만 판단해요.
- 찾은 그림은 시그니처·픽셀 크기를 검사한 뒤 앱이 직접 복사해요. agy에게 복사를 시키지 않아요.
"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from cardnews import config
from cardnews.engines.base import Cancelled, RunContext
from cardnews.errors import AppError
from cardnews.images import files
from cardnews import proc as procs
from cardnews.proc import kill_group
from cardnews.util import now_iso

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TIMEOUT_SECONDS = 300
POLL_SECONDS = 0.5


def _pause(tries: int) -> None:
    """처음엔 짧게, 점점 길게(최대 0.5초) 기다려요. 빨리 끝난 호출을 오래 붙잡지 않게요."""
    time.sleep(min(POLL_SECONDS, 0.02 * (tries + 1)))
AUTH_HINTS = ("sign in", "signed in", "login", "log in", "authenticat", "credential", "401")
TEXT_AREA = {"top": "위쪽", "bottom": "아래쪽", "center": "가운데"}
STYLE = "모든 카드 공통 그림체: 차분한 남색·청록 계열, 단순한 기하학 도형과 부드러운 빛, 평면적인 설명용 일러스트"


def image_prompt(plan: dict, index: int, total: int) -> str:
    area = TEXT_AREA.get(plan["textArea"], "위쪽")
    return f"""내장 이미지 생성 도구로 카드뉴스 배경 그림 한 장을 만들어 주세요 (카드 {index}/{total}).
- 세로 4:5 비율이에요.
- 장면: {plan["prompt"]}
- {STYLE}
- 글자를 올릴 자리: 화면 {area} 약 40%는 비워 두고 단순한 배경만 두세요.
- 그림 안에 글자·숫자·로고·워터마크를 넣지 마세요.
- 실제 제품 화면, 실존 인물, 보도 사진처럼 보이지 않게 그려 주세요.
- 만든 파일을 다른 곳으로 옮기거나 복사하지 마세요."""


def agy_version() -> str:
    try:
        out = subprocess.run([config.agy_bin(), "--version"], capture_output=True, text=True,
                             timeout=20, stdin=subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError) as err:
        raise AppError("TOOL_UNAVAILABLE", "agy를 실행하지 못했어요. Antigravity CLI가 설치돼 있는지 확인해 주세요.") from err
    except subprocess.TimeoutExpired:
        return "agy (버전 확인 실패)"
    return f"agy {out.stdout.strip() or '(버전 모름)'}"


def _run(ctx: RunContext, prompt: str, work_dir: Path) -> subprocess.CompletedProcess:
    args = [config.agy_bin(), "-p", prompt, "--output-format", "json",
            "--print-timeout", f"{TIMEOUT_SECONDS - 60}s"]
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = procs.spawn(args, cwd=work_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    except (FileNotFoundError, PermissionError) as err:
        raise AppError("TOOL_UNAVAILABLE", "agy를 실행하지 못했어요. Antigravity CLI가 설치돼 있는지 확인해 주세요.") from err
    started, tries = time.monotonic(), 0
    try:
        while proc.poll() is None:
            ctx.check_cancel()
            if time.monotonic() - started > TIMEOUT_SECONDS:
                kill_group(proc)
                raise AppError("IMAGE_FAILED", f"agy가 {TIMEOUT_SECONDS // 60}분 안에 끝나지 않았어요.")
            _pause(tries)
            tries += 1
    except Cancelled:
        kill_group(proc)
        raise
    finally:
        procs.release(proc)
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _conversation_id(done: subprocess.CompletedProcess) -> str:
    text = (done.stderr or "") + (done.stdout or "")
    if done.returncode != 0:
        if any(hint in text.lower() for hint in AUTH_HINTS):
            raise AppError("AUTH_REQUIRED", "agy 로그인이 필요해요. 터미널에서 agy를 실행해 로그인해 주세요.")
        first = text.strip().splitlines()[0][:200] if text.strip() else "알 수 없는 오류"
        raise AppError("IMAGE_FAILED", f"agy 실행이 실패했어요: {first}")
    try:
        response = json.loads(done.stdout)
    except json.JSONDecodeError as err:
        raise AppError("IMAGE_FAILED", "agy 응답을 JSON으로 읽지 못했어요.") from err
    cid = str(response.get("conversation_id", ""))
    if not UUID.match(cid):  # 경로 조작을 막으려고 형식부터 확인해요
        raise AppError("IMAGE_FAILED", "agy 응답에 올바른 conversation_id가 없어요.")
    if response.get("status") != "SUCCESS":
        raise AppError("IMAGE_FAILED", f"agy가 실패를 알렸어요: {response.get('status')}")
    return cid


def _wait_for_image(ctx: RunContext, folder: Path, since: float) -> Path:
    deadline, tries = time.monotonic() + config.agy_wait(), 0
    while True:
        found = files.new_images(folder, since)
        if found:
            return found[-1]
        if time.monotonic() >= deadline:
            raise AppError("IMAGE_FAILED", "agy가 끝났는데 새로 만든 그림 파일을 찾지 못했어요.",
                           {"folder": f"brain/{folder.name}"})
        ctx.check_cancel()
        _pause(tries)
        tries += 1


def _check(path: Path) -> tuple[str, int, int]:
    kind, width, height = files.image_info(path) or (None, None, None)
    if kind is None or not width or not height:
        raise AppError("IMAGE_FAILED", "그림 파일의 형식이나 크기를 읽지 못했어요.")
    if min(width, height) < files.MIN_SHORT_SIDE:
        raise AppError("IMAGE_FAILED", f"그림이 너무 작아요 ({width}×{height}).")
    return kind, width, height


def generate(ctx: RunContext, plan: dict, index: int, total: int, dest_stem: Path,
             tool: str) -> dict:
    """그림 한 장을 만들어 dest_stem.<확장자>로 복사하고 생성 기록을 돌려줘요."""
    prompt = image_prompt(plan, index, total)
    since = time.time() - 1
    done = _run(ctx, prompt, ctx.run_dir / "agy")
    cid = _conversation_id(done)
    source = _wait_for_image(ctx, config.agy_brain() / cid, since)
    kind, width, height = _check(source)
    dest = files.with_extension(dest_stem, kind)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    digest = files.sha256(dest)
    if digest != files.sha256(source):
        raise AppError("IMAGE_FAILED", "그림을 복사했는데 원본과 내용이 달라요.")
    return {"origin": "generated", "tool": tool, "conversationId": cid, "prompt": prompt,
            "createdAt": now_iso(), "originalFormat": kind, "originalSize": [width, height],
            "sha256": digest, "disclosure": "생성 이미지", "dest": dest}
