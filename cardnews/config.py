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


def mock_delay() -> float:
    return float(os.environ.get("CARDNEWS_MOCK_DELAY", "0.7"))
