import hashlib
import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Seoul")


def now() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def body_hash(endpoint: str, body: dict) -> str:
    raw = json.dumps({"e": endpoint, "b": body}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
