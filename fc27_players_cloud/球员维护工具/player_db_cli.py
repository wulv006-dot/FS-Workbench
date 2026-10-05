"""FC27 球员数据库只读 CLI。

示例（PowerShell）：

``python -m 球员维护工具.player_db_cli status``

``python -m 球员维护工具.player_db_cli query --q Maradona --page 1 --per-page 20``

``python -m 球员维护工具.player_db_cli export --q Maradona --output evidence/maradona.xlsx``

CLI 只调用 :mod:`player_database` 的只读白名单端点，不触发采集或后台设置。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .player_database import (
    DEFAULT_BASE_URL,
    PLAYER_FILTER_KEYS,
    PlayerDatabaseClient,
    PlayerDatabaseError,
    WorkbookValidationError,
)
from .models import ExportFilters


def _add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    for key in PLAYER_FILTER_KEYS:
        option = "--" + key.replace("_", "-")
        parser.add_argument(option, dest=key, default=None, help=f"API 筛选参数 {key}")


def _filters_from_args(args: argparse.Namespace) -> ExportFilters:
    values = {key: getattr(args, key) for key in PLAYER_FILTER_KEYS if getattr(args, key, None) is not None}
    return ExportFilters(values)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FC27 FUTBIN 球员数据库只读查询/导出")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="数据库服务地址")
    parser.add_argument("--timeout", type=float, default=30.0, help="单次 HTTP 请求超时秒数")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="读取采集状态")
    status.set_defaults(handler=_run_status)

    query = subparsers.add_parser("query", help="分页读取球员 JSON")
    _add_filter_arguments(query)
    query.add_argument("--page", type=int, default=1)
    query.add_argument("--per-page", type=int, default=50)
    query.add_argument("--sort", default="rating")
    query.add_argument("--order", default="desc")
    query.add_argument("--all", action="store_true", help="请求全部匹配结果")
    query.add_argument("--output", type=Path, help="可选 JSON 输出路径；不填则打印到标准输出")
    query.set_defaults(handler=_run_query)

    export = subparsers.add_parser("export", help="下载并验证球员 XLSX")
    _add_filter_arguments(export)
    export.add_argument("--output", required=True, type=Path, help="XLSX 输出路径")
    export.add_argument("--overwrite", action="store_true", help="允许原子替换已有目标文件")
    export.set_defaults(handler=_run_export)
    return parser


def _client(args: argparse.Namespace) -> PlayerDatabaseClient:
    return PlayerDatabaseClient(args.base_url, timeout=args.timeout)


def _run_status(args: argparse.Namespace) -> int:
    _print_json(_client(args).get_status())
    return 0


def _write_or_print(value: Any, output: Path | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    # 查询 JSON 不是状态快照；仍使用临时文件提交，避免中途中断留下半份结果。
    temp = output.with_name(f".{output.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(output)


def _run_query(args: argparse.Namespace) -> int:
    result = _client(args).list_players(
        _filters_from_args(args),
        page=args.page,
        per_page=args.per_page,
        sort=args.sort,
        order=args.order,
        all=args.all,
    )
    _write_or_print(result.to_dict(), args.output)
    return 0


def _run_export(args: argparse.Namespace) -> int:
    validation = _client(args).export_players(
        _filters_from_args(args),
        args.output,
        overwrite=args.overwrite,
    )
    _print_json({"status": "success", "output": str(args.output), "validation": validation.to_dict()})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (PlayerDatabaseError, WorkbookValidationError, OSError, ValueError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

