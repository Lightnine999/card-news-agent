"""실행 명령의 포트 검사 (cardnews/cli.py)."""

import socket

from cardnews import cli, config


def free_port() -> int:
    with socket.socket() as s:
        s.bind((config.HOST, 0))
        return s.getsockname()[1]


def test_port_in_use_by_listener_is_detected():
    with socket.socket() as listener:
        listener.bind((config.HOST, 0))
        listener.listen()
        assert cli.port_is_free(listener.getsockname()[1]) is False


def test_free_port_is_free():
    assert cli.port_is_free(free_port()) is True
