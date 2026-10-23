"""실행 설정. 값은 호출할 때마다 환경변수에서 읽어요(테스트가 바꿀 수 있게)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = "127.0.0.1"  # PRD: 기본은 127.0.0.1에만 바인딩
DEFAULT_PORT = 8765

MAX_CONCURRENT_RUNS = 2  # API_SPEC 4.1 [AI 기본안]
EXPAND_THRESHOLD = 5  # 후보가 이보다 적으면 30일 확장을 물어요
MAX_SELECTION = 3
PERIOD_CHOICES = (7, 30)
PROGRESS_KEEP = 20

# Claude CLI 호출 옵션 (사용자 결정 D10)
CLAUDE_MODEL = "sonnet"
CLAUDE_EFFORT = "medium"


def data_dir() -> Path:
    return Path(os.environ.get("CARDNEWS_DATA_DIR", ROOT / "data"))


def db_path() -> Path:
    return data_dir() / "app.db"


def engine_name() -> str:
    return os.environ.get("CARDNEWS_ENGINE", "claude-cli")  # D2. 화면만 볼 때는 mock


def claude_bin() -> str:
    return os.environ.get("CARDNEWS_CLAUDE_BIN", "claude")


def image_gen() -> str:
    """auto: 모의 엔진 프로젝트는 모의 그림, 나머지는 agy. agy·mock으로 고정할 수도 있어요."""
    return os.environ.get("CARDNEWS_IMAGE_GEN", "auto")


def agy_bin() -> str:
    return os.environ.get("CARDNEWS_AGY_BIN", "agy")


def agy_brain() -> Path:
    """agy가 그림을 저장하는 폴더 (DECISIONS D11)."""
    default = Path.home() / ".gemini" / "antigravity-cli" / "brain"
    return Path(os.environ.get("CARDNEWS_AGY_BRAIN", default))


def agy_wait() -> float:
    """agy가 끝난 뒤 그림 파일이 보일 때까지 기다리는 최대 초 [AI 기본안]."""
    return float(os.environ.get("CARDNEWS_AGY_WAIT", "90"))


# --- 확인용 스위치: 실제 엔진으로 드문 경로를 확인할 때만 켜요. 기본은 꺼져 있어요. ---


def test_ask_question() -> bool:
    """심층 조사에서 독자 질문을 반드시 내게 해요 (질문 → 답변 → 이어가기 확인용)."""
    return os.environ.get("CARDNEWS_TEST_ASK_QUESTION") == "1"


def test_block_search() -> bool:
    """검색 도구(WebSearch·WebFetch)를 막아요 (검색 실패 표시 확인용)."""
    return os.environ.get("CARDNEWS_TEST_BLOCK_SEARCH") == "1"


def mock_delay() -> float:
    return float(os.environ.get("CARDNEWS_MOCK_DELAY", "0.7"))
