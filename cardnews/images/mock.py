"""모의 그림. 모의 엔진 프로젝트에서 agy 할당량을 쓰지 않고 제작 화면을 확인할 때 써요.

표준 라이브러리만으로 위아래로 색이 바뀌는 PNG를 만들어요. 생성 기록에는 origin=mock으로 남아요.
"""

import struct
import zlib
from pathlib import Path

from cardnews.images import files
from cardnews.util import now_iso

WIDTH, HEIGHT = 896, 1200  # 실제 agy 결과와 같은 크기
TOP, BOTTOM = (16, 28, 54), (24, 120, 130)  # 남색 → 청록


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(width: int, height: int, shift: int) -> bytes:
    rows = []
    for y in range(height):
        t = y / (height - 1)
        rgb = bytes(min(255, int(a + (b - a) * t) + shift) for a, b in zip(TOP, BOTTOM))
        rows.append(b"\x00" + rgb * width)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + _chunk(b"IEND", b""))


def generate(ctx, plan: dict, index: int, total: int, dest_stem: Path, tool: str) -> dict:
    ctx.check_cancel()
    dest = files.with_extension(dest_stem, "png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_png(WIDTH, HEIGHT, shift=(index * 9) % 40))  # 카드마다 조금씩 다른 색
    return {"origin": "mock", "tool": tool, "conversationId": None,
            "prompt": f"(모의 그림, 카드 {index}/{total}) {plan['prompt']}", "createdAt": now_iso(),
            "originalFormat": "png", "originalSize": [WIDTH, HEIGHT], "sha256": files.sha256(dest),
            "disclosure": "모의 그림 — 실제 생성 이미지가 아니에요", "dest": dest}
