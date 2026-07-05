from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Read a fixture as raw bytes — mirrors what Response.body actually returns."""

    def _load(name: str) -> bytes:
        return (FIXTURES_DIR / name).read_bytes()

    return _load
