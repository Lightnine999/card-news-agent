"""테스트용 가짜 `agy`. 실제 agy처럼 그림을 자기 폴더(brain/<대화ID>/)에만 저장해요.

받은 인자를 FAKE_AGY_LOG에 남겨요. FAKE_AGY_SCENARIO로 실패 상황을 골라요.
FAKE_AGY_FAIL_ON이 지시문에 들어 있으면 그 호출만 그림을 만들지 않아요(카드 한 장 실패 시험).
"""

import json
import os
import struct
import sys
import time
import uuid
from pathlib import Path


def jpeg(width: int, height: int) -> bytes:
    """시그니처와 SOF 헤더만 맞춘 작은 JPEG 모양 바이트."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"


def main() -> None:
    args = sys.argv[1:]
    if args == ["--version"]:
        print("1.4.5")
        return
    with open(os.environ["FAKE_AGY_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": args, "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
    scenario = os.environ.get("FAKE_AGY_SCENARIO", "ok")
    prompt = args[args.index("-p") + 1]
    if scenario == "auth":
        print("Not signed in. Run agy and sign in with your Google account.", file=sys.stderr)
        sys.exit(1)
    if scenario == "not_json":
        print("이미지 생성을 시작했어요")
        return
    if scenario == "slow":
        Path(os.environ["FAKE_AGY_PID"]).write_text(str(os.getpid()))
        time.sleep(60)
    cid = str(uuid.uuid4())
    folder = Path(os.environ["FAKE_AGY_BRAIN"]) / cid
    folder.mkdir(parents=True)
    fail_on = os.environ.get("FAKE_AGY_FAIL_ON")
    if scenario == "stale":  # 호출 전 시각으로 찍힌 오래된 그림만 있어요
        old = folder / "old_image.jpg"
        old.write_bytes(jpeg(896, 1200))
        past = time.time() - 3600
        os.utime(old, (past, past))
    elif not (fail_on and fail_on in prompt):
        size = (300, 400) if scenario == "tiny" else (896, 1200)
        (folder / f"card_background_{int(time.time() * 1000)}.jpg").write_bytes(jpeg(*size))
        (folder / ".system_generated").mkdir()
    # 실제 agy처럼 status는 SUCCESS이고 응답 글은 "진행 중"이에요
    print(json.dumps({"conversation_id": cid, "status": "SUCCESS",
                      "response": "이미지 생성을 진행 중입니다. 완료되면 알려 드릴게요.",
                      "duration_seconds": 0.1, "num_turns": 1, "denied_actions": None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
