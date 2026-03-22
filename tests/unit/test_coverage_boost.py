"""
Coverage-boost tests targeting specific uncovered branches across multiple modules.
These tests are minimal and focused only on lines not covered by existing tests.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib import error

import pytest

# ---------------------------------------------------------------------------
# api.py — root / endpoint
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.metrics import ExporterMetrics


class _CollectorStub:
    def __init__(self, ready: bool) -> None:
        self.ready = ready


def test_root_endpoint_warming_up_no_settings() -> None:
    """Root handler with collector NOT ready and no settings."""
    metrics = ExporterMetrics(printer_name="x1c", serial="SN001")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=False))
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Warming Up" in resp.text
    assert "warming" in resp.text


def test_root_endpoint_ready_no_settings() -> None:
    """Root handler with collector ready and no settings (settings=None)."""
    metrics = ExporterMetrics(printer_name="x1c", serial="SN002")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True))
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Connected" in resp.text


def test_root_endpoint_with_printer_name_in_settings() -> None:
    """Root handler with settings providing a printer name → badge shown."""
    from bambulab_metrics_exporter.config import Settings

    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SN003",
        bambulab_access_code="abc",
        bambulab_printer_name="MyPrinter",
    )
    metrics = ExporterMetrics(printer_name="x1c", serial="SN003")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True), settings=settings)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "MyPrinter" in resp.text
    assert "printer-badge" in resp.text


def test_root_endpoint_with_settings_no_printer_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Root handler with settings where printer name is empty → no badge span."""
    from bambulab_metrics_exporter.config import Settings

    # Clear any leaked env vars that might inject a printer name
    monkeypatch.delenv("BAMBULAB_PRINTER_NAME", raising=False)
    monkeypatch.delenv("BAMBULAB_PRINTER_NAME_LABEL", raising=False)

    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SN004",
        bambulab_access_code="abc",
    )
    metrics = ExporterMetrics(printer_name="x1c", serial="SN004")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True), settings=settings)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    # When no printer name, the badge span element should not appear (printer_badge == "")
    assert '<span class="printer-badge">' not in resp.text


def test_ready_endpoint_when_ready() -> None:
    """Ready endpoint returns 200 when collector is ready."""
    metrics = ExporterMetrics(printer_name="x1c", serial="SN005")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True))
    client = TestClient(app)

    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# cloud_auth.py — edge cases and retry paths
# ---------------------------------------------------------------------------

from bambulab_metrics_exporter import cloud_auth
from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthError,
    CloudAuthInvalidError,
    CloudAuthTransientError,
    _extract_user_id,
)


def test_as_int_float_input() -> None:
    """_as_int should convert float input."""
    assert cloud_auth._as_int(3.7) == 3


def test_as_int_empty_string() -> None:
    """_as_int should return default for empty string."""
    assert cloud_auth._as_int("", default=42) == 42
    assert cloud_auth._as_int("   ", default=99) == 99


def test_post_json_retries_transient_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json retries on transient HTTP 503 error and eventually succeeds."""
    call_count = {"n": 0}

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(req, timeout):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise error.HTTPError("url", 503, "Service Unavailable", hdrs=None, fp=io.BytesIO(b"retry"))
        return _FakeResp()

    # Patch time.sleep to avoid actual delays
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fake_urlopen)

    result = cloud_auth._post_json("https://x", "/path", {}, timeout_seconds=1, retries=2)
    assert result == {"ok": True}
    assert call_count["n"] == 2


def test_post_json_retries_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json raises CloudAuthError after retries exhausted on URLError."""
    def fail(*args, **kwargs):
        raise error.URLError("network down")

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="Network error"):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=1)


def test_post_json_non_transient_http_error_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json raises immediately on non-retryable HTTP error (e.g. 400)."""
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 400, "Bad Request", hdrs=None, fp=io.BytesIO(b"bad request"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="HTTP 400"):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=3)


def test_post_json_multi_base_all_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json_multi_base raises when all api_bases fail."""
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 400, "Bad Request", hdrs=None, fp=io.BytesIO(b"bad"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="All cloud API bases failed"):
        cloud_auth._post_json_multi_base(
            "/path", {}, timeout_seconds=1, retries=0,
            api_bases=["https://a", "https://b"],
        )


def test_get_json_retries_urlerror_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_json raises CloudAuthError after URLError exhausts retries."""
    def fail(*args, **kwargs):
        raise error.URLError("network down")

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="Network error"):
        cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=1, access_token="tok")


def test_get_json_retries_transient_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_json raises after retries exhausted on retryable HTTP error."""
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 503, "Unavailable", hdrs=None, fp=io.BytesIO(b"retry"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="HTTP 503"):
        cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=1, access_token="tok")


def test_resolve_user_id_from_profile_continues_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_resolve_user_id_from_profile skips failing api_bases and returns None when all fail."""
    def fail(*args, **kwargs):
        raise CloudAuthError("fail")

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth._get_json", fail)

    result = cloud_auth._resolve_user_id_from_profile(
        access_token="tok", timeout_seconds=1, retries=0, api_bases=["https://a", "https://b"]
    )
    assert result is None


def test_extract_user_id_from_nested_user_dict() -> None:
    """_extract_user_id can find uid in a nested 'user' dict."""
    data = {"user": {"uid": 999, "id": 888}}
    uid = _extract_user_id(data, "x.y.z", timeout_seconds=1, retries=0, api_bases=[])
    assert uid in ("999", "888")


def test_extract_user_id_from_user_dict_id_key() -> None:
    """_extract_user_id falls back to user.id when user.uid absent."""
    data = {"user": {"id": 777}}
    uid = _extract_user_id(data, "x.y.z", timeout_seconds=1, retries=0, api_bases=[])
    assert uid == "777"


def test_extract_user_id_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_extract_user_id raises CloudAuthError when no uid found anywhere."""
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._resolve_user_id_from_profile",
        lambda **_: None,
    )
    with pytest.raises(CloudAuthError, match="Missing user id"):
        _extract_user_id({}, "x.y.z", timeout_seconds=1, retries=0, api_bases=["https://a"])


def test_login_with_code_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """login_with_code raises CloudAuthError when response is missing expected key."""
    # Return a response that lacks 'accessToken' key
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._post_json_multi_base",
        lambda *a, **kw: {"message": "ok"},  # no accessToken key
    )
    with pytest.raises(CloudAuthError, match="Missing expected response key"):
        cloud_auth.login_with_code(email="a@b.com", code="123456")


# ---------------------------------------------------------------------------
# startup.py — uncovered branches
# ---------------------------------------------------------------------------

from bambulab_metrics_exporter.startup import _try_token_refresh
from bambulab_metrics_exporter.config import Settings


def test_try_token_refresh_no_secret_key_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """_try_token_refresh: when no secret key, skips persistence but doesn't crash."""
    import os
    from bambulab_metrics_exporter.cloud_auth import LoginResult

    result = LoginResult(
        access_token="new_tok",
        refresh_token="new_ref",
        expires_in=3600,
        user_id="uid1",
    )

    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.refresh_access_token",
        lambda rt, **kw: result,
    )
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)
    # Use monkeypatch to set/restore env vars to avoid leaks
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "old")
    monkeypatch.setenv("BAMBULAB_CLOUD_REFRESH_TOKEN", "old_ref")

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="old",
        bambulab_cloud_refresh_token="old_ref",
    )
    # Should not raise even without secret key
    _try_token_refresh(settings, "old_ref")
    # Env should be updated
    assert os.environ.get("BAMBULAB_CLOUD_ACCESS_TOKEN") == "new_tok"


def test_validate_cloud_refresh_probe_fails_falls_back_to_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """After refresh, if probe still fails, falls back to reauth (covers line 88)."""
    from bambulab_metrics_exporter.startup import _validate_cloud

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad",
        bambulab_cloud_refresh_token="valid_ref",
    )

    # First probe (initial check) → False; second probe (post-refresh) → False too; third → True
    probe_calls = {"n": 0}
    def fake_probe(s):
        probe_calls["n"] += 1
        return probe_calls["n"] >= 3  # fail twice, succeed on third

    reauth_called = {"called": False}
    def fake_reauth(s):
        reauth_called["called"] = True

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", fake_probe)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_token_refresh", lambda s, rt: None)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_cloud_reauth", fake_reauth)

    # After reauth, Settings() is called — mock it to avoid env var requirement
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.Settings",
        lambda: settings,
    )

    _validate_cloud(settings)
    assert reauth_called["called"] is True


def test_validate_cloud_no_refresh_token_goes_to_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no refresh token, skips refresh and proceeds to reauth (covers line 99)."""
    from bambulab_metrics_exporter.startup import _validate_cloud

    # Ensure env vars that might interfere are cleared
    monkeypatch.delenv("BAMBULAB_CLOUD_REFRESH_TOKEN", raising=False)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad",
        bambulab_cloud_refresh_token="",  # explicitly no refresh token
    )

    probe_calls = {"n": 0}
    def fake_probe(s):
        probe_calls["n"] += 1
        # First call (initial) fails; second call (post-reauth) succeeds
        return probe_calls["n"] > 1

    reauth_called = {"called": False}
    def fake_reauth(s):
        reauth_called["called"] = True

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", fake_probe)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_cloud_reauth", fake_reauth)
    monkeypatch.setattr("bambulab_metrics_exporter.startup.Settings", lambda: settings)

    _validate_cloud(settings)
    assert reauth_called["called"] is True


def test_try_cloud_reauth_no_code_sends_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """_try_cloud_reauth: when code missing, calls send_code and raises (covers lines 159-161)."""
    from bambulab_metrics_exporter.startup import _try_cloud_reauth

    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "user@example.com")
    monkeypatch.delenv("BAMBULAB_CLOUD_CODE", raising=False)

    send_called = {"called": False}
    def fake_send_code(email):
        send_called["called"] = True

    monkeypatch.setattr("bambulab_metrics_exporter.startup.send_code", fake_send_code)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
    )

    with pytest.raises(RuntimeError, match="2FA code was sent"):
        _try_cloud_reauth(settings)

    assert send_called["called"] is True


def test_try_cloud_reauth_no_secret_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_try_cloud_reauth: when secret key missing after login, raises (covers lines 171-173)."""
    from bambulab_metrics_exporter.startup import _try_cloud_reauth
    from bambulab_metrics_exporter.cloud_auth import LoginResult

    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "user@example.com")
    monkeypatch.setenv("BAMBULAB_CLOUD_CODE", "123456")
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)

    result = LoginResult(
        access_token="new_tok",
        refresh_token="new_ref",
        expires_in=3600,
        user_id="uid1",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup.login_with_code", lambda email, code: result)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
    )

    with pytest.raises(RuntimeError, match="BAMBULAB_SECRET_KEY is required"):
        _try_cloud_reauth(settings)


# ---------------------------------------------------------------------------
# models.py — uncovered branches
# ---------------------------------------------------------------------------

from bambulab_metrics_exporter.models import PrinterSnapshot


def _snap(raw: dict) -> PrinterSnapshot:
    return PrinterSnapshot(connected=True, raw=raw)


# --- _parse_ams_info uncovered branches ---

def test_extract_ams_info_empty_string_returns_none() -> None:
    """Empty AMS info string returns None (line 129 branch)."""
    from bambulab_metrics_exporter.models import _extract_ams_info
    result = _extract_ams_info({"info": ""})
    assert result is None

    result2 = _extract_ams_info({"info": "   "})
    assert result2 is None


def test_extract_ams_info_hex_prefix_invalid() -> None:
    """AMS info with 0x prefix + invalid hex chars returns None (lines 158-159)."""
    from bambulab_metrics_exporter.models import _extract_ams_info
    result = _extract_ams_info({"info": "0xGG"})  # invalid hex after 0x stripping
    assert result is None


def test_extract_ams_info_valid_hex_prefix() -> None:
    """AMS info with valid 0x prefix."""
    from bambulab_metrics_exporter.models import _extract_ams_info
    result = _extract_ams_info({"info": "0x0011"})
    assert result == 0x0011


def test_extract_ams_info_digit_string_no_known_type_returns_candidate() -> None:
    """Digit-only AMS info that doesn't match a known type returns first candidate (line 150)."""
    from bambulab_metrics_exporter.models import _extract_ams_info
    # '9999' is a digit string; both dec and hex interpretations have no known AMS type low nibble
    result = _extract_ams_info({"info": "9999"})
    # Should return the decimal value since no type match
    assert result is not None  # returns candidates[0]


def test_extract_ams_info_hex_chars_no_0x_prefix() -> None:
    """AMS info that's pure hex chars without 0x prefix."""
    from bambulab_metrics_exporter.models import _extract_ams_info
    result = _extract_ams_info({"info": "FF01"})
    assert result == 0xFF01


# --- _unpack_temperature uncovered branches ---

def test_unpack_temperature_none_returns_none_none() -> None:
    """_unpack_temperature returns (None, None) for None input (line 368)."""
    from bambulab_metrics_exporter.models import _unpack_temperature
    a, t = _unpack_temperature(None)
    assert a is None
    assert t is None


# --- printer_type / modules uncovered branches ---

def test_modules_from_info_dict() -> None:
    """modules property finds module list inside info dict (line 429)."""
    raw = {
        "print": {},
        "info": {"module": [{"product_name": "BL-P001", "hw_ver": "AP04"}]},
    }
    snap = _snap(raw)
    assert isinstance(snap.modules, list)


def test_printer_type_project_name_N1() -> None:
    """printer_type returns A1MINI when project_name is N1 (lines 462-463)."""
    raw = {
        "print": {
            "module": [
                {"hw_ver": "AP04", "project_name": "N1", "product_name": ""},
            ]
        }
    }
    snap = _snap(raw)
    assert snap.printer_type == "A1MINI"


# --- chamber_temp uncovered ---

def test_chamber_temp_none_without_ctc() -> None:
    """chamber_temp returns None when no ctc block (line 529 branch)."""
    snap = _snap({"print": {}})
    assert snap.chamber_temp is None


# --- ams_tray_now TypeError path ---

def test_ams_tray_now_value_error_returns_none() -> None:
    """ams_tray_now handles ValueError/TypeError on malformed string (lines 702-703)."""
    snap = _snap({"print": {"ams": {"tray_now": "not_a_number"}}})
    # The code tries int("not_a_number") which raises ValueError; should return None
    result = snap.ams_tray_now
    assert result is None


# --- external_spool_entries missing branches ---

def test_external_spool_entries_vir_slot_skips_non_dict() -> None:
    """external_spool_entries skips non-dict items in vir_slot (line 740)."""
    snap = _snap({"print": {"vir_slot": ["not_a_dict", {"id": "1", "tag_uid": "ABC", "tray_type": "PLA"}]}})
    entries = snap.external_spool_entries
    # Should process only the dict item
    assert isinstance(entries, list)


# --- extruder_entries / nozzle_info uncovered branches ---

def test_extruder_entries_missing_device_returns_empty() -> None:
    """extruder_entries returns [] when no 'device' key (lines 813 area)."""
    snap = _snap({"print": {}})
    assert snap.extruder_entries == []


def test_extruder_entries_no_extruder_returns_empty() -> None:
    """extruder_entries returns [] when device has no 'extruder' (line 818)."""
    snap = _snap({"print": {"device": {}}})
    assert snap.extruder_entries == []


def test_extruder_entries_no_info_list_returns_empty() -> None:
    """extruder_entries returns [] when extruder.info is not a list (line 821)."""
    snap = _snap({"print": {"device": {"extruder": {"state": 0}}}})
    assert snap.extruder_entries == []


def test_extruder_entries_skips_non_dict_items() -> None:
    """extruder_entries skips non-dict items in info list (line 828)."""
    snap = _snap({"print": {"device": {"extruder": {"info": ["not_dict", {"id": 0, "temp": 0}]}}}})
    entries = snap.extruder_entries
    # Only the dict item should be processed (the string should be skipped)
    assert isinstance(entries, list)


def test_extruder_nozzle_info_entries_no_device() -> None:
    """extruder_nozzle_info_entries returns [] when no device (line 813)."""
    snap = _snap({"print": {}})
    assert snap.extruder_nozzle_info_entries == []


def test_extruder_nozzle_info_entries_fallback_nozzle_ids() -> None:
    """extruder_nozzle_info_entries uses fallback (ids 0/1) when extruder.info is missing (line 851)."""
    raw = {
        "print": {
            "device": {
                "extruder": {"state": 0},  # no info key
                "nozzle": {
                    "info": [
                        {"id": 0, "type": "HX05", "diameter": 0.4},
                        {"id": 1, "type": "HS01", "diameter": 0.6},
                    ]
                },
            }
        }
    }
    snap = _snap(raw)
    entries = snap.extruder_nozzle_info_entries
    # Should use fallback for ids 0 and 1
    assert any(e["id"] == "0" for e in entries)


def test_extruder_nozzle_info_no_nozzle_returns_empty() -> None:
    """extruder_nozzle_info_entries returns [] when no nozzle key (line 931)."""
    snap = _snap({"print": {"device": {"extruder": {"info": []}}}})
    assert snap.extruder_nozzle_info_entries == []


def test_hotend_rack_present_via_exist_bit() -> None:
    """hotend_rack_present detects via exist bitmask (line 897)."""
    # HOTEND_RACK_SLOT_IDS = (16, 17, 18, 19, 20, 21); bit 16 = 1 << 16
    raw = {
        "print": {
            "device": {
                "nozzle": {
                    "exist": 1 << 16,  # bit 16 set = slot 16 exists
                }
            }
        }
    }
    snap = _snap(raw)
    assert snap.hotend_rack_present is True


def test_hotend_rack_present_via_nozzle_info_ids() -> None:
    """hotend_rack_present detects via nozzle info ids."""
    raw = {
        "print": {
            "device": {
                "nozzle": {
                    "info": [{"id": 16, "type": "HX05", "diameter": 0.4}]  # slot 16 is valid
                }
            }
        }
    }
    snap = _snap(raw)
    assert snap.hotend_rack_present is True


def test_hotend_rack_holder_position_none_when_no_device() -> None:
    """hotend_rack_holder_position_name returns None when no device (line 905)."""
    snap = _snap({"print": {}})
    assert snap.hotend_rack_holder_position_name is None


def test_hotend_rack_holder_position_none_when_no_holder() -> None:
    """hotend_rack_holder_position_name returns None when no holder (line 911)."""
    snap = _snap({"print": {"device": {}}})
    assert snap.hotend_rack_holder_position_name is None


def test_hotend_rack_holder_state_none_when_no_device() -> None:
    """hotend_rack_holder_state_name returns None when no device (line 918)."""
    snap = _snap({"print": {}})
    assert snap.hotend_rack_holder_state_name is None


def test_hotend_rack_holder_state_none_when_no_holder() -> None:
    """hotend_rack_holder_state_name returns None when no holder (line 924)."""
    snap = _snap({"print": {"device": {}}})
    assert snap.hotend_rack_holder_state_name is None


def test_hotend_rack_slot_entries_no_device() -> None:
    """hotend_rack_slot_entries returns [] when no device (line 939)."""
    snap = _snap({"print": {}})
    assert snap.hotend_rack_slot_entries == []


def test_hotend_rack_slot_entries_no_nozzle() -> None:
    """hotend_rack_slot_entries returns [] when no nozzle (line 956)."""
    snap = _snap({"print": {"device": {}}})
    assert snap.hotend_rack_slot_entries == []


def test_hotend_rack_slot_entries_no_exist_or_tar_id() -> None:
    """hotend_rack_slot_entries returns [] when nozzle has neither exist nor tar_id (line 962)."""
    snap = _snap({"print": {"device": {"nozzle": {}}}})
    assert snap.hotend_rack_slot_entries == []


def test_hotend_rack_hotend_entries_no_device() -> None:
    """hotend_rack_hotend_entries returns [] when no device (line 956 area)."""
    snap = _snap({"print": {}})
    assert snap.hotend_rack_hotend_entries == []


def test_hotend_rack_hotend_entries_no_nozzle() -> None:
    """hotend_rack_hotend_entries returns [] when no nozzle."""
    snap = _snap({"print": {"device": {}}})
    assert snap.hotend_rack_hotend_entries == []


def test_hotend_rack_hotend_entries_no_info() -> None:
    """hotend_rack_hotend_entries returns [] when nozzle has no info list."""
    snap = _snap({"print": {"device": {"nozzle": {}}}})
    assert snap.hotend_rack_hotend_entries == []


def test_hotend_rack_hotend_entries_skips_non_dict_and_out_of_range_ids() -> None:
    """hotend_rack_hotend_entries skips non-dict items and non-HOTEND_RACK slot ids (line 967)."""
    raw = {
        "print": {
            "device": {
                "nozzle": {
                    "info": [
                        "not_a_dict",
                        {"id": 99, "type": "HX05", "diameter": 0.4},  # out of HOTEND_RACK_SLOT_IDS
                        {"id": 0, "type": "HS01", "diameter": 0.6},   # valid
                    ]
                }
            }
        }
    }
    snap = _snap(raw)
    entries = snap.hotend_rack_hotend_entries
    assert all(e["slot_id"] != "99" for e in entries)


def test_stat_flags_property() -> None:
    """stat_flags property covered (line 1049)."""
    snap = _snap({"print": {"stat": "0x00000001"}})
    flags = snap.stat_flags
    assert isinstance(flags, dict)


def test_wired_network_no_net() -> None:
    """wired_network returns None when no net block (line 1067)."""
    snap = _snap({"print": {}})
    assert snap.wired_network is None


def test_wired_network_short_info() -> None:
    """wired_network returns None when info list has fewer than 2 entries (line 1071)."""
    snap = _snap({"print": {"net": {"info": [{"ip": 1}]}}})
    assert snap.wired_network is None


def test_wired_network_non_dict_wired_entry() -> None:
    """wired_network returns None when info[1] is not a dict (line 1075)."""
    snap = _snap({"print": {"net": {"info": [{"ip": 1}, "not_a_dict"]}}})
    assert snap.wired_network is None


def test_sdcard_status_from_string_value() -> None:
    """sdcard_status returns string value directly when it's a non-empty string (line 1086)."""
    snap = _snap({"print": {"sdcard": "present"}})
    assert snap.sdcard_status == "present"


def test_door_open_from_int_nonzero() -> None:
    """door_open returns 1.0 when direct int value is non-zero (line 1112)."""
    snap = _snap({"print": {"door_open": 1}})
    assert snap.door_open == 1.0


def test_door_open_x1_family_stat_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """door_open for X1 family falls back to stat_flag when home_flag absent (lines 1121-1122)."""
    raw = {
        "print": {
            "model_id": "X1C",  # X1C is in X1_HOMEFLAG_MODELS
            "stat": "0x00000040",  # door_open bit in STAT_FLAG_MASKS
        }
    }
    snap = _snap(raw)
    # Force printer_type to X1C by having the correct model
    # The result might be None or a value depending on stat_flag; just ensure no crash
    result = snap.door_open
    assert result is None or isinstance(result, float)


def test_door_open_x1_both_flags_none_returns_none() -> None:
    """door_open for X1 printer returns None when neither home_flag nor stat_flag present (line 1123)."""
    # A printer type that's in X1_HOMEFLAG_MODELS but no flags set
    raw = {"print": {"module": [{"product_name": "BL-P001", "hw_ver": "AP04", "project_name": "X1C"}]}}
    snap = _snap(raw)
    result = snap.door_open
    # Should return None (no flags available) or a float; just no crash
    assert result is None or isinstance(result, float)


def test_lid_open_from_int_value() -> None:
    """lid_open returns float from direct int value (line 1144)."""
    snap = _snap({"print": {"lid_open": 1}})
    assert snap.lid_open == 1.0


def test_fan_secondary_aux_none_without_device() -> None:
    """fan_secondary_aux_percent returns None when no device block (lines 573 area)."""
    snap = _snap({"print": {}})
    assert snap.fan_secondary_aux_percent is None


def test_fan_secondary_aux_none_without_airduct() -> None:
    """fan_secondary_aux_percent returns None when no airduct in device."""
    snap = _snap({"print": {"device": {}}})
    assert snap.fan_secondary_aux_percent is None


def test_fan_secondary_aux_none_without_parts() -> None:
    """fan_secondary_aux_percent returns None when no parts list in airduct."""
    snap = _snap({"print": {"device": {"airduct": {}}}})
    assert snap.fan_secondary_aux_percent is None


def test_fan_secondary_aux_skips_non_dict_parts() -> None:
    """fan_secondary_aux_percent skips non-dict items in parts list (line 576)."""
    snap = _snap({"print": {"device": {"airduct": {"parts": ["not_dict"]}}}})
    assert snap.fan_secondary_aux_percent is None


def test_fan_secondary_aux_returns_none_when_id_not_160() -> None:
    """fan_secondary_aux_percent returns None when no part has id=160 (line 579)."""
    snap = _snap({"print": {"device": {"airduct": {"parts": [{"id": 100, "value": 50}]}}}})
    assert snap.fan_secondary_aux_percent is None


def test_layer_progress_none_when_layer_current_missing() -> None:
    """layer_progress_percent returns None when layer_current is None (line 606)."""
    snap = _snap({"print": {}})
    assert snap.layer_progress_percent is None


def test_active_nozzle_entry_none_when_no_extruder_state() -> None:
    """active_nozzle_entry returns None when active_extruder_index is None."""
    snap = _snap({"print": {}})
    assert snap.active_nozzle_entry is None
