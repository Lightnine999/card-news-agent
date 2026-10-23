"""`uv run cardnews` — 웹 서버와 작업 프로세스를 함께 띄워요 (API_SPEC 4.1)."""

import argparse
import socket
import subprocess
import sys

import uvicorn

from cardnews import config, db


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # uvicorn과 같은 옵션이에요. 방금 끈 서버의 끝나는 중인 연결 때문에 "사용 중"으로 잘못 보지 않게요.
        # 다른 프로그램이 실제로 듣고 있으면 이 옵션을 켜도 bind가 실패해요.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((config.HOST, port))
        except OSError:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="카드뉴스 에이전트 로컬 서버")
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    args = parser.parse_args()

    if not port_is_free(args.port):
        print(f"포트 {args.port}을(를) 이미 다른 프로그램이 쓰고 있어요.\n"
              f"다른 포트로 실행해 주세요: uv run cardnews --port {args.port + 1}",
              file=sys.stderr)
        sys.exit(1)

    db.init_db()
    worker = subprocess.Popen([sys.executable, "-m", "cardnews.worker"])
    print(f"엔진: {config.engine_name()}  ·  열기: http://{config.HOST}:{args.port}")
    try:
        uvicorn.run("cardnews.app:app", host=config.HOST, port=args.port, log_level="warning")
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()


if __name__ == "__main__":
    main()
