"""MCP 管理端 CLI：创建账号、充值、改套餐、查用量（Token 只在创建时显示一次）。

用法（python -m mcp.admin ...）：
  create-account --name 张三 --plan starter [--credits 1000]
  add-credits    --account acc_xxx --amount 500 [--note 充值]
  set-plan       --account acc_xxx --plan pro
  set-status     --account acc_xxx --status suspended|active
  list           # 全部账号
  plans          # 套餐清单
  usage          --account acc_xxx [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import sys

from showly_mcp import accounts_db, billing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp.admin", description="Showly MCP 管理端")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-account", help="创建账号并生成 Token")
    p.add_argument("--name", required=True)
    p.add_argument("--plan", required=True, help="free / starter / pro")
    p.add_argument("--credits", type=float, default=0)

    p = sub.add_parser("add-credits", help="充值积分")
    p.add_argument("--account", required=True)
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--note", default="")

    p = sub.add_parser("set-plan", help="修改套餐")
    p.add_argument("--account", required=True)
    p.add_argument("--plan", required=True)

    p = sub.add_parser("set-status", help="停用/启用账号")
    p.add_argument("--account", required=True)
    p.add_argument("--status", required=True, choices=["active", "suspended"])

    sub.add_parser("list", help="账号列表")
    sub.add_parser("plans", help="套餐列表")

    p = sub.add_parser("usage", help="账号用量")
    p.add_argument("--account", required=True)
    p.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    accounts_db.connect()  # 确保建库
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create-account":
            account = billing.create_account(args.name, args.plan,
                                             initial_credits=args.credits)
            print(f"账号创建成功：{account['id']}（{account['name']} · {account['plan']}）")
            print(f"Token（只显示这一次，请妥善保存）：\n  {account['token']}")
            print("用户 MCP 配置：URL 指向 <服务地址>/mcp，请求头 Authorization: Bearer <上面的 Token>")
        elif args.command == "add-credits":
            account = billing.add_credits(args.account, args.amount, args.note)
            print(f"已充值 {args.amount:g} 积分；余额 {account['credits']:g}")
        elif args.command == "set-plan":
            account = billing.set_plan(args.account, args.plan)
            print(f"套餐已改为 {account['plan_id']}（{account.get('plan_name', '')}）")
        elif args.command == "set-status":
            account = billing.set_status(args.account, args.status)
            print(f"状态已改为 {account['status']}")
        elif args.command == "list":
            rows = billing.list_accounts()
            print(f"{'ID':<18} {'名称':<12} {'套餐':<10} {'积分':>8} {'状态':<10} 调用数")
            for r in rows:
                print(f"{r['id']:<18} {r['name'][:12]:<12} {r['plan_id']:<10}"
                      f" {r['credits']:>8g} {r['status']:<10} {r['total_calls']}")
        elif args.command == "plans":
            for plan in billing.list_plans():
                print(f"{plan['id']:<10} {plan['name']:<10} 工具：{','.join(plan['allowed_tools'])}"
                      f"  {plan['note']}")
        elif args.command == "usage":
            rows = billing.account_usage(args.account, args.limit)
            if not rows:
                print("暂无调用记录")
            for r in rows:
                mark = "✓" if r["ok"] else "✗"
                print(f"{r['created_at']} {mark} {r['tool']:<8} {r['credits_cost']:>6g}"
                      f"  {r['error'][:60]}")
        return 0
    except billing.QuotaError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
