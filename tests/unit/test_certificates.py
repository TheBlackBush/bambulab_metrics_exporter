"""Printer certificate check for `auto` hosts: CA check, pins, and the in-handshake hook."""
from __future__ import annotations

import json
import ssl
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest
from certgen import TlsServer, forged_leaf, make_ca, make_leaf

from bambulab_metrics_exporter import certificates as certs
from bambulab_metrics_exporter.certificates import (
    CertificateCheck,
    CertificateRejected,
    PinStore,
    checked_context,
    describe,
    load_anchors,
    pretty_fingerprint,
)
from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient
from bambulab_metrics_exporter.config import Settings

SERIAL = "00MFAKETEST0001"
OTHER = "00MFAKETEST0002"


def _check(tmp_path: Path, anchors=()) -> tuple[CertificateCheck, PinStore]:
    pins = PinStore(tmp_path / certs.PINS_FILE)
    return CertificateCheck(SERIAL, pins, anchors=tuple(anchors)), pins


def test_describe_reads_the_leaf_facts() -> None:
    ca = make_ca()
    leaf = make_leaf(SERIAL, ca)
    cert, facts = describe(leaf.der)
    assert cert is not None
    assert facts.subject_cn == SERIAL
    assert "CN=Fake Test Printer CA" in facts.issuer
    assert (facts.not_before, facts.not_after) == ("2026-01-01T00:00:00Z", "2035-12-30T00:00:00Z")
    assert len(facts.fingerprint) == 64 and facts.fingerprint == facts.fingerprint.lower()


@pytest.mark.parametrize("der", [None, b"", b"not a certificate"])
def test_no_or_garbage_certificate_is_rejected(tmp_path: Path, der) -> None:
    check, pins = _check(tmp_path)
    with pytest.raises(CertificateRejected) as caught:
        check.verify(der)
    assert caught.value.facts.result == certs.UNREADABLE
    assert "did not send the access code" in str(caught.value)
    check.connected()
    assert pins.get(SERIAL) is None


def test_ca_signed_leaf_with_the_serial_is_accepted_and_pinned(tmp_path: Path) -> None:
    ca = make_ca()
    leaf = make_leaf(SERIAL, ca)
    check, pins = _check(tmp_path, [ca.cert])
    assert check.verify(leaf.der).result == certs.CA_VERIFIED
    assert pins.get(SERIAL) is None  # pinned only once the printer accepts the login
    check.connected()
    assert pins.get(SERIAL) == describe(leaf.der)[1].fingerprint


def test_ca_signed_leaf_for_another_serial_is_rejected(tmp_path: Path) -> None:
    ca = make_ca()
    check, _ = _check(tmp_path, [ca.cert])
    with pytest.raises(CertificateRejected) as caught:
        check.verify(make_leaf(OTHER, ca).der)
    assert caught.value.facts.result == certs.CN_MISMATCH


def test_leaf_naming_the_ca_but_not_signed_by_it_is_rejected(tmp_path: Path) -> None:
    ca = make_ca()
    check, pins = _check(tmp_path, [ca.cert])
    pins.set(SERIAL, describe(forged_leaf(SERIAL, ca).der)[1].fingerprint)
    with pytest.raises(CertificateRejected) as caught:
        check.verify(forged_leaf(SERIAL, ca).der)
    assert caught.value.facts.result == certs.CA_FAILED


def test_a_new_ca_signed_leaf_replaces_the_pin(tmp_path: Path) -> None:
    ca = make_ca()
    check, pins = _check(tmp_path, [ca.cert])
    pins.set(SERIAL, "0" * 64)
    renewed = make_leaf(SERIAL, ca)
    assert check.verify(renewed.der).result == certs.CA_VERIFIED
    check.connected()
    assert pins.get(SERIAL) == describe(renewed.der)[1].fingerprint


def test_first_use_pins_then_the_same_certificate_passes(tmp_path: Path) -> None:
    leaf = make_leaf(SERIAL)
    check, pins = _check(tmp_path, [make_ca().cert])  # a CA that did not issue this leaf
    assert check.verify(leaf.der).result == certs.FIRST_USE
    check.connected()
    check.connected()  # only one pending pin
    assert check.verify(leaf.der).result == certs.PINNED
    assert CertificateCheck(SERIAL, PinStore(tmp_path / certs.PINS_FILE), anchors=()).verify(
        leaf.der
    ).result == certs.PINNED  # survives a restart


def test_first_use_does_not_check_the_common_name(tmp_path: Path) -> None:
    check, _ = _check(tmp_path)
    assert check.verify(make_leaf("printer").der).result == certs.FIRST_USE


def test_a_different_certificate_is_rejected_as_changed(tmp_path: Path) -> None:
    first, second = make_leaf(SERIAL), make_leaf(SERIAL)
    check, pins = _check(tmp_path)
    check.verify(first.der)
    check.connected()
    with pytest.raises(CertificateRejected) as caught:
        check.verify(second.der)
    facts = caught.value.facts
    assert facts.result == certs.CHANGED and facts.rejected
    assert facts.pinned == describe(first.der)[1].fingerprint
    assert str(caught.value).startswith("Certificate changed")
    check.connected()  # a rejected certificate is never pinned
    assert pins.get(SERIAL) == describe(first.der)[1].fingerprint
    assert check.last == facts


def test_a_failed_login_does_not_pin(tmp_path: Path) -> None:
    check, pins = _check(tmp_path)
    check.verify(make_leaf(SERIAL).der)
    assert pins.get(SERIAL) is None  # connected() never ran: CONNACK refused


def test_trust_pins_only_the_rejected_certificate(tmp_path: Path) -> None:
    first, second = make_leaf(SERIAL), make_leaf(SERIAL)
    check, pins = _check(tmp_path)
    assert check.trust("0" * 64) is False  # nothing rejected yet
    check.verify(first.der)
    check.connected()
    with pytest.raises(CertificateRejected):
        check.verify(second.der)
    new = describe(second.der)[1].fingerprint
    assert check.trust(describe(first.der)[1].fingerprint) is False
    assert check.trust(new.upper()) is False
    assert check.trust(new) is True
    assert pins.get(SERIAL) == new
    assert check.verify(second.der).result == certs.PINNED


def test_pins_are_per_serial_and_stored_without_the_serial(tmp_path: Path) -> None:
    pins = PinStore(tmp_path / certs.PINS_FILE)
    pins.set(SERIAL, "a" * 64)
    pins.set(OTHER.lower(), "b" * 64)
    assert pins.get(SERIAL.lower()) == "a" * 64 and pins.get(OTHER) == "b" * 64
    path = tmp_path / certs.PINS_FILE
    text = path.read_text()
    assert SERIAL not in text and OTHER not in text
    assert json.loads(text)["format"] == 1
    assert path.stat().st_mode & 0o777 == 0o600


def test_pin_store_uses_the_config_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path / "cfg"))
    PinStore().set(SERIAL, "c" * 64)
    assert (tmp_path / "cfg" / certs.PINS_FILE).exists()


def test_unreadable_pins_are_kept_aside_and_logged_without_content(
    tmp_path: Path, caplog
) -> None:
    path = tmp_path / certs.PINS_FILE
    path.write_text("{not json")
    pins = PinStore(path)
    assert pins.get(SERIAL) is None
    assert pins.damaged
    assert (tmp_path / certs.UNREADABLE_PINS_FILE).read_text() == "{not json"
    assert "could not be read" in caplog.text
    assert "not json" not in caplog.text


def test_with_unreadable_pins_an_unpinned_certificate_is_rejected_not_first_use(
    tmp_path: Path,
) -> None:
    path = tmp_path / certs.PINS_FILE
    path.write_text("{not json")
    check = CertificateCheck(SERIAL, PinStore(path), anchors=())
    leaf = make_leaf(SERIAL)
    fingerprint = describe(leaf.der)[1].fingerprint
    with pytest.raises(CertificateRejected) as caught:
        check.verify(leaf.der)
    facts = caught.value.facts
    assert facts.result == certs.CHANGED and facts.fingerprint == fingerprint
    assert facts.pinned == ""
    check.connected()  # a rejected certificate is never pinned
    assert path.read_text() == "{not json"


def test_trusting_the_rejected_certificate_rewrites_a_valid_pins_file(tmp_path: Path) -> None:
    path = tmp_path / certs.PINS_FILE
    path.write_text("{not json")
    check = CertificateCheck(SERIAL, PinStore(path), anchors=())
    leaf = make_leaf(SERIAL)
    fingerprint = describe(leaf.der)[1].fingerprint
    with pytest.raises(CertificateRejected):
        check.verify(leaf.der)
    assert check.trust(fingerprint) is True
    assert check.verify(leaf.der).result == certs.PINNED
    saved = json.loads(path.read_text())
    assert saved["format"] == 1 and list(saved["pins"].values()) == [fingerprint]
    assert (tmp_path / certs.UNREADABLE_PINS_FILE).read_text() == "{not json"


def test_with_unreadable_pins_a_ca_verified_leaf_still_passes(tmp_path: Path) -> None:
    path = tmp_path / certs.PINS_FILE
    path.write_text("{not json")
    ca = make_ca()
    check = CertificateCheck(SERIAL, PinStore(path), anchors=(ca.cert,))
    assert check.verify(make_leaf(SERIAL, ca).der).result == certs.CA_VERIFIED


def test_pin_entries_that_are_not_fingerprints_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / certs.PINS_FILE
    path.write_text(json.dumps({"format": 1, "pins": {"k": "not-a-fingerprint"}}))
    assert PinStore(path).get(SERIAL) is None


def test_pins_that_cannot_be_saved_last_for_the_session(tmp_path: Path, caplog) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    pins = PinStore(blocker / certs.PINS_FILE)  # parent is a file: mkdir fails
    pins.set(SERIAL, "d" * 64)
    assert pins.get(SERIAL) == "d" * 64
    assert "lasts until the next restart" in caplog.text


def test_load_anchors_reads_every_pem_and_skips_bad_files(tmp_path: Path, caplog) -> None:
    one, two = make_ca("Fake One"), make_ca("Fake Two")
    (tmp_path / "a.pem").write_bytes(one.pem + two.pem)
    (tmp_path / "b.pem").write_bytes(b"-----BEGIN CERTIFICATE-----\nbroken\n")
    (tmp_path / "c.txt").write_bytes(one.pem)
    assert [a.subject for a in load_anchors(tmp_path)] == [one.cert.subject, two.cert.subject]
    assert "b.pem" in caplog.text
    assert load_anchors(tmp_path / "missing") == ()


def test_packaged_ca_directory_loads() -> None:
    assert isinstance(certs.bambu_anchors(), tuple)


def test_pretty_fingerprint_matches_openssl_style() -> None:
    assert pretty_fingerprint("ab01" * 2) == "AB:01:AB:01"


def test_checks_are_shared_by_settings_copies(tmp_path: Path) -> None:
    import copy

    check, _ = _check(tmp_path)
    assert copy.deepcopy(check) is check


# -- in the handshake, before CONNECT --------------------------------------------------


def _paho(context: ssl.SSLContext) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set("bblp", "fake-access-code")
    client.tls_set_context(context)
    client.tls_insecure_set(True)
    return client


def _context(check: CertificateCheck) -> ssl.SSLContext:
    context = checked_context(check)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def test_a_rejected_certificate_never_gets_connect(tmp_path: Path) -> None:
    check, pins = _check(tmp_path)
    pins.set(SERIAL, "e" * 64)
    with TlsServer(make_leaf(SERIAL)) as server:
        client = _paho(_context(check))
        with pytest.raises(CertificateRejected):
            client.connect("127.0.0.1", server.port, keepalive=5)
        assert server.finished.wait(5)
    assert server.handshake_done.is_set()
    assert server.received == b""  # no CONNECT, so no access code
    assert check.last is not None and check.last.result == certs.CHANGED


def test_an_accepted_certificate_lets_paho_send_connect(tmp_path: Path) -> None:
    check, _ = _check(tmp_path)
    with TlsServer(make_leaf(SERIAL)) as server:
        client = _paho(_context(check))
        client.connect("127.0.0.1", server.port, keepalive=5)
        client.disconnect()
        assert server.finished.wait(5)
    assert server.received[:1] == b"\x10"  # MQTT CONNECT
    assert check.last is not None and check.last.result == certs.FIRST_USE


def test_local_client_with_a_check_refuses_before_connect(tmp_path: Path) -> None:
    check, pins = _check(tmp_path)
    pins.set(SERIAL, "e" * 64)
    with TlsServer(make_leaf(SERIAL)) as server:
        settings = Settings(
            bambulab_host="auto", bambulab_serial=SERIAL, bambulab_access_code="fake-access-code"
        ).with_certificate_check(
            check, {"bambulab_host": "127.0.0.1", "bambulab_port": server.port}
        )
        client = LocalMqttBambuClient(settings)
        with pytest.raises(CertificateRejected):
            client.connect()
        client.disconnect()
        assert server.finished.wait(5)
    assert server.received == b""
