"""Shared fixtures. Fake secrets and emails are assembled at run time so that no
secret-looking string is stored in the repository (secret scanners stay quiet)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
FAKE_BEARER = "Bearer " + "t" * 8 + "EST" + "0" * 20          # matches bearer_literal, not a real token
FAKE_EMAIL = "jane.doe" + "@" + "gmail.com"                     # looks personal on purpose


def build_broken(tmp_dir: Path) -> Path:
    text = (FIX / "broken.template.json").read_text(encoding="utf-8")
    headers = {"parameters": [{"name": "Author" + "ization", "value": FAKE_BEARER}]}
    text = text.replace('"__HEADERS__"', json.dumps(headers)).replace("__EMAIL__", FAKE_EMAIL)
    out = tmp_dir / "broken.json"
    out.write_text(text, encoding="utf-8")
    return out


@pytest.fixture
def broken_path(tmp_path: Path) -> Path:
    return build_broken(tmp_path)


@pytest.fixture
def broken(broken_path: Path) -> dict:
    return json.loads(broken_path.read_text(encoding="utf-8"))


@pytest.fixture
def clean() -> dict:
    return json.loads((FIX / "clean.json").read_text(encoding="utf-8"))
