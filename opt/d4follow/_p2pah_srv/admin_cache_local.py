"""RPG Admin cache client; authentication belongs to the existing FS 8767 owner."""
import argparse
import datetime as dt
import json
import sys

from fc_shared_admin import SessionManager

TYPES = {"tp": "清理系统缓存", "opcache": "清除PHP全部缓存",
         "storage": "清理浏览器缓存", "all": "一键清理所有"}


def log(message):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), message), flush=True)


def load_token():
    owner = SessionManager({})
    return owner.token if owner.ensure() else None


def clear_cache(type_="all", token=None):
    if type_ not in TYPES:
        return 0, "invalid_cache_type"
    token = token or load_token()
    if not token:
        return 503, "shared_admin_unavailable"
    owner = SessionManager({"P2PAH_API_BASE": "https://admin-api.p2pah.cn"})
    try:
        status, body = owner.request("/admin/tools.Caches/clear?server=1",
                                     data={"type": type_, "file": ""}, token=token)
        return status, body.decode("utf-8", "replace")
    except (OSError, ValueError) as error:
        # A sent POST may have succeeded; never repeat it on a transport failure.
        return 0, "admin_clear_outcome_unknown:%s" % type(error).__name__


def cmd_status(args):
    token = load_token()
    log("FS 全局 Admin 会话：%s" % ("ready" if token else "unavailable"))
    if getattr(args, "probe", False) and token:
        return cmd_clear(args)
    return 0 if token else 3


def cmd_login(args):
    return cmd_status(args)


def cmd_clear(args):
    if getattr(args, "token", None):
        log("请使用 FS 全局 8767 会话，不接受独立凭证")
        return 2
    status, body = clear_cache(getattr(args, "type", "all"))
    try:
        result = json.loads(body)
        ok = status == 200 and isinstance(result, dict) and result.get("code") == 1
    except (ValueError, TypeError):
        ok = False
    log("主后台清缓存：%s（HTTP %s）" % ("confirmed" if ok else "unconfirmed", status))
    return 0 if ok else 4


def main():
    parser = argparse.ArgumentParser(description="通过 FS 全局会话清理 Admin 缓存")
    commands = parser.add_subparsers(dest="cmd")
    for name, handler in (("login", cmd_login), ("clear", cmd_clear), ("status", cmd_status)):
        command = commands.add_parser(name)
        command.set_defaults(func=handler)
        if name == "clear":
            command.add_argument("--type", default="all", choices=list(TYPES))
            command.add_argument("--token", help=argparse.SUPPRESS)
            command.add_argument("--no-auto", action="store_true", help=argparse.SUPPRESS)
            command.add_argument("--headful", action="store_true", help=argparse.SUPPRESS)
        elif name == "status":
            command.add_argument("--probe", action="store_true", help="真实清一次 all 缓存")
        else:
            for flag in ("user", "password", "wait"):
                command.add_argument("--" + flag, help=argparse.SUPPRESS)
            for flag in ("manual", "headful", "keep-open"):
                command.add_argument("--" + flag, action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
