"""Shared test fixtures."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_environment() -> Iterator[None]:
    """Startup, runtime and /auth code write os.environ directly (by design); restore it
    after every test so values never leak between tests."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
