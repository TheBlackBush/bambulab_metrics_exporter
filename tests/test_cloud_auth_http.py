from __future__ import annotations

import io
import json
from urllib import error

import pytest

from bambulab_metrics_exporter import cloud_auth


class _Resp:
    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {}

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_post_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", lambda *a, **k: _Resp({"ok": True}))
    data = cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=0)
    assert data["ok"] is True


def test_post_json_http_403_1010(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"error code: 1010"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)
    with pytest.raises(cloud_auth.CloudAuthError):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=0)


def test_post_json_multi_base_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(base: str, *args, **kwargs):
        if base == "https://a":
            raise cloud_auth.CloudAuthError("bad a")
        return {"ok": True}

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth._post_json", fake_post)
    data = cloud_auth._post_json_multi_base("/p", {}, 1, 0, ["https://a", "https://b"])
    assert data["ok"] is True


def test_get_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", lambda *a, **k: _Resp({"uid": 1}))
    data = cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=0, access_token="t")
    assert data["uid"] == 1


def test_resolve_user_id_from_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._get_json",
        lambda *a, **k: {"uid": 99},
    )
    assert cloud_auth._resolve_user_id_from_profile("t", 1, 0, ["https://x"]) == "99"
