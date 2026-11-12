"""Run the console or existing RPG suites through pr-fast's offline guards."""
import argparse
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
import pr_fast


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("console", "rpg", "all"), default="console")
    args = parser.parse_args()
    if args.group in ("console", "all"):
        pr_fast.units("releases/rpg-console/console-v2-20261112/tests",
                      ["test_game_parameters", "test_console_config", "test_integration",
                       "test_safety_review", "test_release_safety"])
    if args.group in ("rpg", "all"):
        pr_fast.units("tools", ["pr_fast_tests.RPGGuards", "pr_fast_tests.RPGModuleContracts"])
        pr_fast.units("opt/d4follow", ["test_wow_sources", "test_iggm_local_first"])


if __name__ == "__main__":
    main()
