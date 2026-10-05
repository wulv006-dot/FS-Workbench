from __future__ import annotations

import argparse
import json

from .collection import collect_only
from .repository import Repository
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FC27 Players 云端只读维护 CLI")
    parser.add_argument("command", choices=("init-db", "migrate-feature-parity", "collect-only", "status", "import-legacy-blocks"))
    parser.add_argument("--days-new", type=int, choices=(1, 3, 7, 14, 30))
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    repository = Repository(settings.data_root / "db" / "control.sqlite3")
    if args.command == "init-db":
        repository.initialize()
        print("state_db_initialized")
    elif args.command == "migrate-feature-parity":
        repository.migrate_feature_parity()
        print("feature_parity_schema_2_migrated")
    elif args.command == "collect-only":
        print(json.dumps(collect_only(settings, repository, days_new=args.days_new), ensure_ascii=False))
    elif args.command == "import-legacy-blocks":
        source = settings.data_root / "imports" / "legacy_unresolved.json"
        records = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("旧端未决清单必须是数组")
        print(json.dumps({"legacy_unresolved_ids": repository.import_legacy_blocks(records)}, ensure_ascii=False))
    else:
        print(json.dumps({"latest": repository.latest_collection(),
                          "latest_success": repository.last_successful_collection(),
                          "jobs": repository.status_counts(),
                          "write_enabled": settings.write_enabled}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
