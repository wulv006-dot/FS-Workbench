"""Repository-relative paths and synthetic fixtures; no production config reads."""
import json
from pathlib import Path
import sys

RELEASE = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]
APP = REPO / "opt" / "d4follow"
FIXTURES = RELEASE / "fixtures"
sys.path.insert(0, str(APP))


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


SETTINGS = fixture("settings.json")
MAIN = SETTINGS["common"]
SEP = {"wow_gold_config.json": SETTINGS["wow"], "aa_gold_config.json": SETTINGS["aa"]}
