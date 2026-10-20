#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs-iam 运维命令行
===================

控制台能做的事这里都能做，另外多了「不带界面的判定」——排障时最快：

    python3 admin_cli.py status
    python3 admin_cli.py members
    python3 admin_cli.py roles
    python3 admin_cli.py check --user mmoexp --method POST --uri /d4/api/price
    python3 admin_cli.py grant --user zhang --roles PricingOps --by chenchao --note "接手 D4"
    python3 admin_cli.py revoke --user zhang --role PricingOps --by chenchao

所有写操作与控制台走同一条 `rbac.save_policy()`：原子落盘、自动备份、
追加审计、并强制「至少保留一名超级管理员」。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import rbac  # noqa: E402


def _policy():
    return rbac.load_policy()


def cmd_status(args):
    policy = _policy()
    print("策略文件     %s" % rbac.LIVE_POLICY)
    print("版本         #%s  (修订 %s)" % (policy.get("generation"), rbac.revision_of(policy)))
    print("最后更新     %s by %s" % (policy.get("updated_at"), policy.get("updated_by")))
    print("超级管理员   %s" % "、".join(sorted(rbac.admins(policy))))
    print("默认角色     %s" % (policy.get("unbound_role") or "（严格拒绝未分配者）"))
    print("角色 %d 个    绑定 %d 条" % (len(policy.get("roles") or {}),
                                       len(policy.get("bindings") or {})))
    if os.path.exists(rbac.AUDIT_LOG):
        print("审计日志     %s (%d 字节)" % (rbac.AUDIT_LOG, os.path.getsize(rbac.AUDIT_LOG)))
    return 0


def cmd_members(args):
    policy = _policy()
    rows = sorted((policy.get("bindings") or {}).items())
    print("%-24s %-28s %s" % ("成员", "角色", "身份"))
    for subject, binding in rows:
        roles = (binding.get("roles") if isinstance(binding, dict) else binding) or []
        print("%-24s %-28s %s" % (subject, ",".join(roles) or "-",
                                  "管理员" if rbac.is_admin(policy, subject) else "普通"))
    if not rows:
        print("(没有任何绑定)")
    return 0


def cmd_roles(args):
    policy = _policy()
    for name, role in (policy.get("roles") or {}).items():
        used = [s for s, b in (policy.get("bindings") or {}).items()
                if name in ((b.get("roles") if isinstance(b, dict) else b) or [])]
        print("%s  %s  [%d 名成员]" % (name, role.get("label") or "", len(used)))
        print("    %s" % rbac.summarize_role(role))
    return 0


def cmd_check(args):
    policy = _policy()
    decision = rbac.evaluate(policy, args.user, args.method, args.uri, args.group)
    data = decision.as_dict()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("\n结论：%s (%d)" % ("允许" if data["allow"] else "拒绝", data["code"]))
    return 0 if data["allow"] else 3


def cmd_explain(args):
    return cmd_check(args)


def cmd_grant(args):
    policy = _policy()
    subject = args.user
    binding = policy.setdefault("bindings", {}).get(subject)
    if isinstance(binding, dict):
        current = list(binding.get("roles") or [])
    elif isinstance(binding, list):
        current = list(binding)
    else:
        current = []
    wanted = [r.strip() for r in str(args.roles).split(",") if r.strip()]
    if not wanted:
        print("--roles 为空", file=sys.stderr)
        return 1
    roles = sorted(set(current) | set(wanted))
    unknown = [r for r in roles if r not in (policy.get("roles") or {})]
    if unknown:
        print("角色不存在：%s" % ",".join(unknown), file=sys.stderr)
        return 1
    policy["bindings"][subject] = {"roles": roles}
    rbac.validate(policy)
    if not rbac.is_admin(policy, args.by):
        print("操作人 %s 不是超级管理员，拒绝执行" % args.by, file=sys.stderr)
        return 1
    rev = rbac.save_policy(policy, args.by, note=args.note or "CLI grant %s" % subject)
    print("%s → %s  修订 %s" % (subject, ",".join(roles), rev))
    return 0


def cmd_revoke(args):
    policy = _policy()
    subject = args.user
    binding = policy.get("bindings", {}).get(subject)
    if not binding:
        print("%s 没有绑定" % subject, file=sys.stderr)
        return 1
    current = binding.get("roles") if isinstance(binding, dict) else binding
    roles = [r for r in (current or []) if r != args.role]
    if isinstance(binding, dict):
        binding["roles"] = roles
        if not roles and not binding.get("grants"):
            policy["bindings"].pop(subject, None)
    elif roles:
        policy["bindings"][subject] = roles
    else:
        policy["bindings"].pop(subject, None)
    rbac.validate(policy)
    if not rbac.is_admin(policy, args.by):
        print("操作人 %s 不是超级管理员，拒绝执行" % args.by, file=sys.stderr)
        return 1
    if subject == args.by and not rbac.is_admin(policy, args.by):
        print("会把自己踢出管理员，已阻止", file=sys.stderr)
        return 1
    rev = rbac.save_policy(policy, args.by, note=args.note or "CLI revoke %s" % subject)
    print("%s 剩余角色 %s  修订 %s" % (subject, ",".join(roles) or "无", rev))
    return 0


def cmd_audit(args):
    for entry in rbac.read_audit(limit=args.limit):
        print("%s  %-10s  #%s  %s" % (
            entry.get("at"), entry.get("actor"), entry.get("generation"), entry.get("note")))
        for change in entry.get("changes") or []:
            print("    %s" % json.dumps(change, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="fs-iam 运维命令行")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("members").set_defaults(func=cmd_members)
    sub.add_parser("roles").set_defaults(func=cmd_roles)

    for name in ("check", "explain"):
        p = sub.add_parser(name)
        p.add_argument("--user", required=True)
        p.add_argument("--method", default="GET")
        p.add_argument("--uri", required=True)
        p.add_argument("--group", default="")
        p.set_defaults(func=cmd_check if name == "check" else cmd_explain)

    p = sub.add_parser("grant")
    p.add_argument("--user", required=True)
    p.add_argument("--roles", required=True, help="逗号分隔")
    p.add_argument("--by", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_grant)

    p = sub.add_parser("revoke")
    p.add_argument("--user", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("audit")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
