"""Certificates generated for tests: a fake CA, printer leaves, and a loopback TLS server.

Nothing here is Bambu Lab data. The server listens on 127.0.0.1 only (allowed by the network
guard in conftest.py) and records whether the client sent any bytes after the handshake.
"""
from __future__ import annotations

import datetime as dt
import socket
import ssl
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@dataclass
class Issued:
    cert: x509.Certificate
    key: ec.EllipticCurvePrivateKey

    @property
    def der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    @property
    def pem(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.PEM)


def _name(common_name: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Fake Test CA Org"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def make_ca(common_name: str = "Fake Test Printer CA") -> Issued:
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name)).issuer_name(_name(common_name))
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_NOW).not_valid_after(_NOW + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return Issued(cert, key)


def make_leaf(common_name: str, issuer: Issued | None = None) -> Issued:
    """A printer certificate; self-signed when `issuer` is None."""
    key = ec.generate_private_key(ec.SECP256R1())
    signer_name = issuer.cert.subject if issuer else _name(common_name)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name)).issuer_name(signer_name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_NOW).not_valid_after(_NOW + dt.timedelta(days=3650))
        .sign(issuer.key if issuer else key, hashes.SHA256())
    )
    return Issued(cert, key)


def forged_leaf(common_name: str, ca: Issued) -> Issued:
    """Names `ca` as its issuer but is signed by another key."""
    return make_leaf(common_name, Issued(ca.cert, ec.generate_private_key(ec.SECP256R1())))


@dataclass
class TlsServer:
    """One-connection TLS server on 127.0.0.1 presenting `leaf`."""

    leaf: Issued
    port: int = 0
    received: bytes = b""
    handshake_done: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)

    def __enter__(self) -> TlsServer:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        with tempfile.TemporaryDirectory() as folder:
            cert_path, key_path = Path(folder, "c.pem"), Path(folder, "k.pem")
            cert_path.write_bytes(self.leaf.pem)
            key_path.write_bytes(self.leaf.key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            context.load_cert_chain(cert_path, key_path)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(5)
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, args=(context,), daemon=True)
        self._thread.start()
        return self

    def _serve(self, context: ssl.SSLContext) -> None:
        try:
            raw, _ = self._listener.accept()
            with context.wrap_socket(raw, server_side=True) as conn:
                self.handshake_done.set()
                conn.settimeout(2)
                try:
                    while chunk := conn.recv(4096):
                        self.received += chunk
                except (OSError, ssl.SSLError):
                    pass
        except OSError:
            pass
        finally:
            self.finished.set()

    def __exit__(self, *exc: object) -> None:
        self._listener.close()
        self._thread.join(5)
