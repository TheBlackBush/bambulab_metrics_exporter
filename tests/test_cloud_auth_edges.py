from __future__ import annotations

import io
from urllib import error

import pytest

from bambulab_metrics_exporter import cloud_auth


def test_post_json_urlerror_raises_when_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error.URLError("net")),
    )
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda *_: None)
    with pytest.raises(cloud_auth.CloudAuthError):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=0)


def test_get_json_http_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 401, "unauthorized", hdrs=None, fp=io.BytesIO(b"denied"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)
    with pytest.raises(cloud_auth.CloudAuthError):
        cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=0, access_token="t")


def test_build_parser_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", "/tmp/conf")
    parser = cloud_auth._build_parser()
    args = parser.parse_args(["--email", "user@example.com", "--send-code"])
    assert args.config_dir == "/tmp/conf"
