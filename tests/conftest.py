"""Shared test fixtures."""
from __future__ import annotations

import os
import socket
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_environment() -> Iterator[None]:
    """Startup, runtime and /auth code write os.environ directly (by design); restore it
    and the /auth page's record of original values after every test."""
    from bambulab_metrics_exporter import overrides, startup

    saved = dict(os.environ)
    overrides._ORIGINAL_ENV.clear()
    startup.reset_legacy_login_state()
    yield
    os.environ.clear()
    os.environ.update(saved)
    overrides._ORIGINAL_ENV.clear()
    startup.reset_legacy_login_state()


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never reach a real printer, broker or Bambu Cloud: fail any outbound
    connection or DNS lookup instead of silently going online."""
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host in _LOCAL_HOSTS:
            return real_connect(self, address)
        raise RuntimeError(f"network access blocked in tests: {address!r}")

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object):
        if isinstance(host, str) and host not in _LOCAL_HOSTS:
            raise RuntimeError(f"network access blocked in tests: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
