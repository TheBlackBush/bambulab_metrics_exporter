"""Printer certificate check for LAN printers found with `auto`.

The LAN access code is the MQTT password, so the printer's certificate is checked inside the
TLS handshake, before paho sends CONNECT. paho 2.1 wraps the socket with
`do_handshake_on_connect=False`, calls `do_handshake()` itself in `_ssl_wrap_socket` and only
then sends CONNECT from `reconnect()`; that is true for the first connection and for paho's own
reconnects. `CheckedContext` hands paho a socket class whose `do_handshake()` runs the check, so
a rejected certificate closes the connection before any MQTT byte is written.

A certificate is accepted when:

- it is issued by a Bambu Lab CA certificate packaged in `certs/` and its common name is the
  printer's serial number, or
- no packaged CA issued it, and it is the certificate pinned for the serial. With no pin yet
  (first use), it is pinned once the printer accepts the connection.

Anything else is rejected; there is no fallback to an unchecked connection. When the pins file
cannot be read, no certificate gets first use for the rest of the process (see `PinStore`).
Fixed hosts and Bambu Cloud are not checked (unchanged behavior). OpenSSL verification stays
off: the leaf is checked here, so a printer whose chain OpenSSL would refuse (unknown root)
still works with a pin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import ssl
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.x509.oid import NameOID

from bambulab_metrics_exporter.credentials_store import write_private_file
from bambulab_metrics_exporter.overrides import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

PINS_FILE = "printer-certificates.json"
UNREADABLE_PINS_FILE = f"{PINS_FILE}.bad"
CA_DIR = Path(__file__).parent / "certs"

CA_VERIFIED = "ca"
PINNED = "pinned"
FIRST_USE = "first_use"
CHANGED = "changed"
CA_FAILED = "ca_failed"
CN_MISMATCH = "cn_mismatch"
UNREADABLE = "unreadable"
REJECTED = frozenset({CHANGED, CA_FAILED, CN_MISMATCH, UNREADABLE})

_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_MESSAGES = {
    CHANGED: (
        "Certificate changed: the printer at the announced address shows a different "
        "certificate than before, so the exporter did not send the access code. If you updated "
        "the firmware or replaced the printer, trust the new certificate on the /auth page."
    ),
    CA_FAILED: (
        "Certificate not signed by Bambu Lab: the printer's certificate names a Bambu Lab CA "
        "but its signature does not match, so the exporter did not send the access code."
    ),
    CN_MISMATCH: (
        "Certificate for another printer: the certificate's serial number is not this "
        "printer's, so the exporter did not send the access code."
    ),
    UNREADABLE: (
        "No readable certificate: the printer sent no certificate the exporter can read, so "
        "it did not send the access code."
    ),
}


@dataclass(frozen=True, slots=True)
class CertificateFacts:
    """What one handshake showed. `fingerprint` is the SHA-256 of the leaf (lowercase hex);
    `pinned` is the pin it was compared with when the result is CHANGED (empty when the pins
    file was unreadable and there was nothing to compare with)."""

    result: str
    fingerprint: str = ""
    subject_cn: str = ""
    issuer: str = ""
    not_before: str = ""
    not_after: str = ""
    pinned: str = ""

    @property
    def rejected(self) -> bool:
        return self.result in REJECTED


class CertificateRejected(ssl.SSLCertVerificationError):
    """Raised inside the TLS handshake. It is an OSError, so paho treats it as a failed
    connection (and retries in its network thread) and never sends CONNECT."""

    def __init__(self, facts: CertificateFacts) -> None:
        super().__init__(rejection_message(facts))
        self.facts = facts

    def __str__(self) -> str:
        return rejection_message(self.facts)


def rejection_message(facts: CertificateFacts) -> str:
    return _MESSAGES.get(facts.result, _MESSAGES[UNREADABLE])


def pretty_fingerprint(fingerprint: str) -> str:
    """`AB:CD:...`, as `openssl x509 -fingerprint -sha256` prints it."""
    upper = fingerprint.upper()
    return ":".join(upper[i:i + 2] for i in range(0, len(upper), 2))


def load_anchors(directory: Path) -> tuple[x509.Certificate, ...]:
    """Every certificate in `directory/*.pem`. A missing directory gives none."""
    anchors: list[x509.Certificate] = []
    for path in sorted(directory.glob("*.pem")):
        try:
            anchors.extend(x509.load_pem_x509_certificates(path.read_bytes()))
        except (OSError, ValueError):
            logger.warning("Ignoring the unreadable CA certificate file %s", path.name)
    return tuple(anchors)


@lru_cache(maxsize=1)
def bambu_anchors() -> tuple[x509.Certificate, ...]:
    """The packaged Bambu Lab CA certificates (`certs/*.pem`)."""
    return load_anchors(CA_DIR)


def _utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(der: bytes | None) -> tuple[x509.Certificate | None, CertificateFacts]:
    """Parse the leaf. No certificate, or one that does not parse, is UNREADABLE."""
    if not der:
        return None, CertificateFacts(UNREADABLE)
    fingerprint = hashlib.sha256(der).hexdigest()
    try:
        cert = x509.load_der_x509_certificate(der)
        names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        facts = CertificateFacts(
            result="",
            fingerprint=fingerprint,
            subject_cn=str(names[0].value) if names else "",
            issuer=cert.issuer.rfc4514_string(),
            not_before=_utc(cert.not_valid_before_utc),
            not_after=_utc(cert.not_valid_after_utc),
        )
    except ValueError:
        return None, CertificateFacts(UNREADABLE, fingerprint)
    return cert, facts


def _signed_by_anchor(
    cert: x509.Certificate, anchors: tuple[x509.Certificate, ...]
) -> bool | None:
    """None when no packaged CA has the leaf's issuer name; else whether one signed it."""
    candidates = [anchor for anchor in anchors if anchor.subject == cert.issuer]
    if not candidates:
        return None
    for anchor in candidates:
        try:
            cert.verify_directly_issued_by(anchor)
        except (ValueError, TypeError, InvalidSignature):
            continue
        return True
    return False


class PinStore:
    """SHA-256 pins of printer certificates, one per serial, in BAMBULAB_CONFIG_DIR.

    Plain JSON with mode 0600, so it works without BAMBULAB_SECRET_KEY and in both run modes
    (env printer or saved list): a fingerprint is not a secret, since any device on the LAN can
    read the certificate. Serials are stored hashed. When the file cannot be written, pins last
    until the next restart.

    When the file exists but cannot be read, it is kept as `.bad` and the store is `damaged`
    for the rest of the process: forgetting the pins must not turn the next certificate into a
    trusted first use. `CertificateCheck` therefore rejects every unpinned certificate until it
    is trusted explicitly, which pins it and writes a fresh, valid file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._fixed_path = path
        self._lock = threading.Lock()
        self._pins: dict[str, str] | None = None
        self._damaged = False

    def _path(self) -> Path:
        if self._fixed_path is not None:
            return self._fixed_path
        return Path(os.getenv("BAMBULAB_CONFIG_DIR", DEFAULT_CONFIG_DIR)) / PINS_FILE

    @staticmethod
    def _key(serial: str) -> str:
        return hashlib.sha256(serial.strip().upper().encode("utf-8")).hexdigest()[:24]

    def _load(self) -> dict[str, str]:
        """The pins, read once. The caller holds the lock."""
        if self._pins is not None:
            return self._pins
        path = self._path()
        pins: dict[str, str] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw.get("pins") if isinstance(raw, dict) else None
            if not isinstance(items, dict):
                raise ValueError("no pins in the file")
            pins = {
                key: value for key, value in items.items()
                if isinstance(key, str) and isinstance(value, str)
                and _FINGERPRINT_RE.fullmatch(value)
            }
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self._damaged = True
            logger.warning(
                "The printer certificate pins (%s) could not be read (%s); kept as %s. "
                "Printers found with auto are refused until you trust their certificate "
                "on the /auth page",
                PINS_FILE, type(exc).__name__, UNREADABLE_PINS_FILE,
            )
            try:
                write_private_file(path.with_name(UNREADABLE_PINS_FILE), path.read_bytes())
            except OSError:
                pass
        self._pins = pins
        return pins

    @property
    def damaged(self) -> bool:
        """True when the pins file could not be read at startup (for the whole process)."""
        with self._lock:
            self._load()
            return self._damaged

    def get(self, serial: str) -> str | None:
        with self._lock:
            return self._load().get(self._key(serial))

    def set(self, serial: str, fingerprint: str) -> None:
        with self._lock:
            pins = self._load()
            key = self._key(serial)
            if pins.get(key) == fingerprint:
                return
            pins[key] = fingerprint
            data = json.dumps({"format": 1, "pins": pins}, indent=1, sort_keys=True)
            try:
                write_private_file(self._path(), data.encode("utf-8"))
            except OSError as exc:
                logger.warning(
                    "Could not save the printer certificate pin (%s); it lasts until the "
                    "next restart", exc.strerror or type(exc).__name__,
                )


class CertificateCheck:
    """Checks one printer's certificate in every TLS handshake of its clients (the startup
    probe and the collector, paho's reconnects included). Copies of the settings share it."""

    def __init__(
        self,
        serial: str,
        pins: PinStore,
        anchors: tuple[x509.Certificate, ...] | None = None,
    ) -> None:
        self._serial = serial.strip().upper()
        self._pins = pins
        self._anchors = bambu_anchors() if anchors is None else anchors
        self._lock = threading.Lock()
        self._last: CertificateFacts | None = None
        self._pending = ""

    def __deepcopy__(self, memo: dict[int, object]) -> CertificateCheck:
        return self  # shared state: a settings copy must keep the same check

    @property
    def last(self) -> CertificateFacts | None:
        """The result of the latest handshake; None before the first one."""
        with self._lock:
            return self._last

    def verify(self, der: bytes | None) -> CertificateFacts:
        """Judge the leaf. Raises CertificateRejected when it must not get the access code."""
        cert, facts = describe(der)
        if cert is not None:
            facts = self._judge(cert, facts)
        with self._lock:
            self._last = facts
            self._pending = facts.fingerprint if facts.result in (CA_VERIFIED, FIRST_USE) else ""
        if facts.rejected:
            raise CertificateRejected(facts)
        return facts

    def _judge(self, cert: x509.Certificate, facts: CertificateFacts) -> CertificateFacts:
        signed = _signed_by_anchor(cert, self._anchors)
        if signed is not None:
            if not signed:
                return replace(facts, result=CA_FAILED)
            if facts.subject_cn.strip().upper() != self._serial:
                return replace(facts, result=CN_MISMATCH)
            return replace(facts, result=CA_VERIFIED)
        pinned = self._pins.get(self._serial)
        if pinned is None:
            if self._pins.damaged:
                # The pins were lost, not absent: do not trust this certificate on first use.
                return replace(facts, result=CHANGED)
            return replace(facts, result=FIRST_USE)
        if pinned == facts.fingerprint:
            return replace(facts, result=PINNED)
        return replace(facts, result=CHANGED, pinned=pinned)

    def connected(self) -> None:
        """The printer accepted the connection (CONNACK 0): pin a first-use or CA-verified
        certificate, so a later certificate must match it."""
        with self._lock:
            fingerprint, self._pending = self._pending, ""
        if fingerprint:
            self._pins.set(self._serial, fingerprint)

    def trust(self, fingerprint: str) -> bool:
        """Pin the certificate the latest handshake rejected as changed, if it is
        `fingerprint` (what the page showed). False when that is not the current rejection."""
        with self._lock:
            last = self._last
        if last is None or last.result != CHANGED or last.fingerprint != fingerprint:
            return False
        self._pins.set(self._serial, fingerprint)
        return True


class _CheckedSocket(ssl.SSLSocket):
    def do_handshake(self, block: bool = False) -> None:
        super().do_handshake(block)
        context = self.context
        if not isinstance(context, CheckedContext) or context.certificate_check is None:
            return
        try:
            context.certificate_check.verify(self.getpeercert(binary_form=True))
        except CertificateRejected:
            self.close()
            raise


class CheckedContext(ssl.SSLContext):
    """An SSLContext whose sockets run `certificate_check` right after the handshake."""

    certificate_check: CertificateCheck | None = None


def checked_context(check: CertificateCheck) -> ssl.SSLContext:
    context = CheckedContext(ssl.PROTOCOL_TLS_CLIENT)
    context.certificate_check = check
    context.sslsocket_class = _CheckedSocket
    return context
