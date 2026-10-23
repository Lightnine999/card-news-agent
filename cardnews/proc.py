"""하위 프로세스(claude, agy) 실행과 정리.

claude·agy는 따로 끝낼 수 있게 새 프로세스 그룹으로 띄워요. 그래서 터미널의 Ctrl+C가 직접 닿지 않아요.
작업 프로세스가 꺼질 때(Ctrl+C, 서버 종료, 부모 사라짐) kill_all()로 띄운 것을 모두 끝내요.
그러지 않으면 앱을 꺼도 엔진 호출이 혼자 계속 돌아 사용량이 나가요.
"""

import os
import signal
import subprocess
import threading

_active: set[subprocess.Popen] = set()
_lock = threading.Lock()


def spawn(args: list[str], **kwargs) -> subprocess.Popen:
    """인자 배열로 새 프로세스 그룹에서 실행하고, 꺼질 때 정리할 목록에 올려요."""
    proc = subprocess.Popen(args, start_new_session=True, **kwargs)
    with _lock:
        _active.add(proc)
    return proc


def release(proc: subprocess.Popen) -> None:
    with _lock:
        _active.discard(proc)


def kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    finally:
        release(proc)


def kill_all() -> int:
    with _lock:
        procs = list(_active)
    for proc in procs:
        kill_group(proc)
    return len(procs)
