"""Tests for the send-code ladder on the /auth page."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from bambulab_metrics_exporter import auth_actions
from bambulab_metrics_exporter.auth_actions import AuthInputError, CodeSender, SendCodeLimiter
from bambulab_metrics_exporter.cloud_auth import CloudAuthError

EMAIL = "operator@example.invalid"


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _round(limiter: SendCodeLimiter, clock: Clock, sends: int = 5) -> None:
    for _ in range(sends):
        limiter.check_and_record()
        clock.advance(60)


def test_sixty_second_spacing(tmp_path: Path) -> None:
    clock = Clock()
    limiter = SendCodeLimiter(tmp_path / "s.json", clock)
    limiter.check_and_record()
    clock.advance(59)
    with pytest.raises(AuthInputError, match="Try again in 1 seconds"):
        limiter.check_and_record()
    clock.advance(1)
    limiter.check_and_record()


def test_fifth_send_starts_ten_minute_lock(tmp_path: Path) -> None:
    clock = Clock()
    limiter = SendCodeLimiter(tmp_path / "s.json", clock)
    _round(limiter, clock, sends=5)  # clock is 60 s past the fifth send
    with pytest.raises(AuthInputError, match="9 minutes"):
        limiter.check_and_record()
    clock.advance(539)
    with pytest.raises(AuthInputError):
        limiter.check_and_record()
    clock.advance(1)
    limiter.check_and_record()


def test_second_and_third_rounds_lock_for_one_hour(tmp_path: Path) -> None:
    clock = Clock()
    limiter = SendCodeLimiter(tmp_path / "s.json", clock)
    _round(limiter, clock)
    clock.advance(600)
    for _ in range(2):
        _round(limiter, clock)
        with pytest.raises(AuthInputError, match="59 minutes"):
            limiter.check_and_record()
        clock.advance(3600)


def test_reset_returns_to_round_one(tmp_path: Path) -> None:
    clock = Clock()
    limiter = SendCodeLimiter(tmp_path / "s.json", clock)
    _round(limiter, clock)
    limiter.reset()
    _round(limiter, clock)
    with pytest.raises(AuthInputError, match="9 minutes"):  # 10 minute step, not 1 hour
        limiter.check_and_record()


def test_restart_keeps_the_lock(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "s.json"
    _round(SendCodeLimiter(path, clock), clock)
    with pytest.raises(AuthInputError, match="minutes"):
        SendCodeLimiter(path, clock).check_and_record()


def test_state_file_holds_no_email_and_is_private(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    path = tmp_path / "s.json"
    CodeSender(SendCodeLimiter(path, Clock())).send(EMAIL)
    assert "example" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_default_path_is_in_the_config_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    SendCodeLimiter(clock=Clock()).check_and_record()
    assert (tmp_path / "send-code-limit.json").exists()


def test_rejected_send_counts(tmp_path: Path, monkeypatch) -> None:
    def fail(email: str) -> None:
        raise CloudAuthError("network down")

    monkeypatch.setattr(auth_actions, "send_code", fail)
    clock = Clock()
    sender = CodeSender(SendCodeLimiter(tmp_path / "s.json", clock))
    assert not sender.send(EMAIL).ok
    with pytest.raises(AuthInputError, match="Try again"):
        sender.send(EMAIL)


def test_invalid_email_does_not_count(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    with pytest.raises(AuthInputError):
        CodeSender(SendCodeLimiter(path, Clock())).send("not-an-email")
    assert not path.exists()


def test_future_timestamps_are_capped(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "round": 2, "sends": 5, "last_send": clock.now + 86400, "locked_until": clock.now + 86400,
    }))
    limiter = SendCodeLimiter(path, clock)
    with pytest.raises(AuthInputError, match="60 minutes"):
        limiter.check_and_record()
    clock.advance(3600)
    limiter.check_and_record()


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"round": "x"}',
        '{"round": 1, "sends": null}',
        '{"round": Infinity, "sends": 1, "last_send": 0, "locked_until": 0}',
    ],
)
def test_corrupt_state_file_gives_fresh_ladder(tmp_path: Path, content: str) -> None:
    path = tmp_path / "s.json"
    path.write_text(content)
    SendCodeLimiter(path, Clock()).check_and_record()


def test_unwritable_state_file_keeps_ladder_in_memory(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    limiter = SendCodeLimiter(blocker / "s.json", Clock())
    limiter.check_and_record()
    with pytest.raises(AuthInputError, match="Try again"):
        limiter.check_and_record()


def test_concurrent_sends_count_once_within_interval(tmp_path: Path, monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    sender = CodeSender(SendCodeLimiter(tmp_path / "s.json", Clock()))

    def press() -> None:
        try:
            sender.send(EMAIL)
        except AuthInputError:
            pass

    threads = [threading.Thread(target=press) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(sent) == 1
