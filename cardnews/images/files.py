"""그림 파일 검사: 확장자가 아니라 파일 앞부분(시그니처)으로 형식을, 헤더로 실제 픽셀 크기를 읽어요."""

import hashlib
import struct
from pathlib import Path

MIN_SHORT_SIDE = 512  # 이보다 작으면 카드 배경으로 못 써요 [AI 기본안]
HEAD_BYTES = 256 * 1024
CONTENT_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
EXTENSIONS = {"png": "png", "jpeg": "jpg", "webp": "webp"}


def _jpeg_size(head: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(head):
        if head[i] != 0xFF:
            i += 1
            continue
        marker = head[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", head[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            height, width = struct.unpack(">HH", head[i + 5:i + 9])
            return width, height
        i += 2 + length
    return None


def _webp_size(head: bytes) -> tuple[int, int] | None:
    chunk = head[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", head[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def image_info(path: Path) -> tuple[str, int | None, int | None] | None:
    """(형식, 너비, 높이). 그림이 아니면 None."""
    with path.open("rb") as f:
        head = f.read(HEAD_BYTES)
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
        return ("png", *struct.unpack(">II", head[16:24]))
    if head.startswith(b"\xff\xd8\xff"):
        return ("jpeg", *(_jpeg_size(head) or (None, None)))
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ("webp", *(_webp_size(head) or (None, None)))
    return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_images(folder: Path, since: float) -> list[Path]:
    """since 이후에 바뀐 그림 파일만, 오래된 것부터. 심볼릭 링크는 따라가지 않아요."""
    if not folder.is_dir() or folder.is_symlink():
        return []
    found = [p for p in folder.rglob("*")
             if p.is_file() and not p.is_symlink() and p.stat().st_mtime >= since and image_info(p)]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def with_extension(stem: Path, kind: str) -> Path:
    """stem 뒤에 확장자를 붙여요. card_1.v2 → card_1.v2.jpg (with_suffix는 .v2를 확장자로 보고 지워요)."""
    return stem.parent / f"{stem.name}.{EXTENSIONS[kind]}"


def content_type(path: Path) -> str | None:
    info = image_info(path)
    return CONTENT_TYPES[info[0]] if info else None
