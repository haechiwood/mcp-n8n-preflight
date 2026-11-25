"""Command line use without an MCP client (for CI or a quick check).

  n8n-preflight lint <workflow.json> [--profile run|share|template] [--json]
  n8n-preflight rules

Exit code: 0 = no errors, 1 = at least one error finding, 2 = usage or input problem.
Does not need the MCP SDK; standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys

from .rules import RULES, lint


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="n8n-preflight")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint")
    p.add_argument("file")
    p.add_argument("--profile", default="share", choices=["run", "share", "template"])
    p.add_argument("--json", action="store_true")
    sub.add_parser("rules")
    a = ap.parse_args(argv)

    if a.cmd == "rules":
        for k, v in RULES.items():
            print(f"{k}  {v['severity']:<7} {v['category']:<11} {v['title']}")
        return 0
    try:
        with open(a.file, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"n8n-preflight: cannot read {a.file}: {e.__class__.__name__}", file=sys.stderr)
        return 2
    wfs = data if isinstance(data, list) else [data]
    try:
        results = [lint(wf, a.profile) for wf in wfs]
    except ValueError as e:
        print(f"n8n-preflight: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            c = r["counts"]
            print(f"{r['workflow']}: {c['error']} error, {c['warning']} warning, {c['info']} info ({r['profile']})")
            for f in r["findings"]:
                node = f" [{f['node']}]" if f["node"] else ""
                print(f"  {f['severity']:<7} {f['rule']}{node} {f['message']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
