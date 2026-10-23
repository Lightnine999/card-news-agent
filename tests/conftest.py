import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 테스트마다 빈 data 폴더와 지연 없는 모의 엔진을 써요
    monkeypatch.setenv("CARDNEWS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CARDNEWS_ENGINE", "mock")
    monkeypatch.setenv("CARDNEWS_MOCK_DELAY", "0")
    from cardnews import db
    from cardnews.app import app

    db.init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def run_worker():
    """작업 프로세스가 할 일을 테스트 안에서 바로 끝까지 처리해요."""
    from cardnews import worker

    def _run():
        worker.run_pending()

    return _run


def rid() -> str:
    return str(uuid.uuid4())
