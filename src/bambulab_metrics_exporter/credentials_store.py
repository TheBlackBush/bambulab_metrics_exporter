from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from bambulab_metrics_exporter.security import decrypt_json, encrypt_json, ensure_parent


def write_private_file(path: Path, data: bytes) -> None:
    """Replace ``path`` atomically with a 0600 file: a crash leaves the old file or the new
    one, never a truncated one. mkstemp creates the temp file 0600 whatever the umask."""
    ensure_parent(path)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def save_encrypted_credentials(path: Path, secret: str, payload: dict[str, Any]) -> None:
    write_private_file(path, encrypt_json(secret, json.dumps(payload, ensure_ascii=False)))


def load_encrypted_credentials(path: Path, secret: str) -> dict[str, Any]:
    blob = path.read_bytes()
    plaintext = decrypt_json(secret, blob)
    raw = json.loads(plaintext)
    if not isinstance(raw, dict):
        raise ValueError("Credentials payload must be a JSON object")
    return raw
