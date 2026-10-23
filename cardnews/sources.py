"""엔진이 실제로 열어 본 URL을 모으고 후보 출처와 맞춰요.

"열어 봄"은 엔진의 WebFetch 결과 코드가 2xx인 경우만이에요. 검색 결과에 나온 것,
403처럼 막힌 것, 결과가 오지 않은 것은 열어 본 것이 아니에요.
엔진이 출처를 official로 적어도 열어 보지 않았으면 화면에 "출처 미확인"을 보여 줘요.
"""

from urllib.parse import urlsplit, urlunsplit


def normalize(url: str) -> str:
    """같은 페이지를 같은 문자열로: 대소문자·www.·끝 슬래시·#조각은 무시하고 ?쿼리는 남겨요."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = f":{parts.port}" if parts.port else ""
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host + port, path, parts.query, ""))


class FetchTracker:
    """stream-json 이벤트를 한 줄씩 받아 성공한 WebFetch URL을 모아요."""

    def __init__(self) -> None:
        self._pending: dict[str, str] = {}  # tool_use_id → 요청한 URL
        self.opened: set[str] = set()

    def feed(self, event: dict) -> None:
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            return
        for part in content:
            if part.get("type") == "tool_use" and part.get("name") == "WebFetch":
                url = (part.get("input") or {}).get("url")
                if url:
                    self._pending[part.get("id")] = url
            elif part.get("type") == "tool_result" and part.get("tool_use_id") in self._pending:
                self._record(self._pending.pop(part["tool_use_id"]), event.get("tool_use_result"))

    def _record(self, requested: str, result) -> None:
        if not isinstance(result, dict) or not isinstance(result.get("code"), int):
            return
        if 200 <= result["code"] < 300:
            self.opened.add(requested)
            if result.get("url"):
                self.opened.add(result["url"])  # 넘겨준 주소(redirect)도 같은 페이지로 봐요


def merge(old: list[str], new: list[str]) -> list[str]:
    return sorted(set(old) | set(new))


def mark(candidates: list[dict], opened: list[str]) -> list[dict]:
    """출처마다 opened를 붙인 새 목록을 돌려줘요. 원본은 바꾸지 않아요."""
    seen = {normalize(u) for u in opened}
    return [{**c, "sources": [{**s, "opened": normalize(s["url"]) in seen} for s in c["sources"]]}
            for c in candidates]
