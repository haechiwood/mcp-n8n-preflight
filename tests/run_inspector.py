#!/usr/bin/env python3
"""Run end-to-end MCP cases through the official MCP Inspector CLI (stdio).

Creates a temporary N8N_PREFLIGHT_ROOT with the test workflows, runs each case as
`mcp-inspector --cli ... -- python -m n8n_preflight.server`, checks the output, and writes
  tests/logs/inspector-stdio.txt   raw Inspector output per case (temp paths redacted)
  tests/logs/summary.md.txt        case table

Env:
  INSPECTOR  command for the Inspector (default: "npx -y @modelcontextprotocol/inspector@2.16.0")
  PYTHON     interpreter that has this package installed (default: sys.executable)
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from conftest import FAKE_BEARER, FAKE_EMAIL, FIX, build_broken  # noqa: E402

LOGS = HERE / "logs"
INSPECTOR = shlex.split(os.environ.get("INSPECTOR", "npx -y @modelcontextprotocol/inspector@2.16.0"))
PY = os.environ.get("PYTHON", sys.executable)
TMP = Path(tempfile.mkdtemp(prefix="preflight-root-")).resolve()
OUTSIDE = Path(tempfile.mkdtemp(prefix="preflight-outside-")).resolve()


def redact(s: str) -> str:
    for k, label in ((str(TMP), "<ROOT>"), (str(OUTSIDE), "<OUTSIDE>"), (shlex.join(INSPECTOR), "mcp-inspector"),
                     (PY, "python"), (str(HERE.parent), "."), (os.path.expanduser("~"), "~")):
        s = s.replace(k, label)
    return s


def target(write: bool) -> list[str]:
    env = ["-e", f"N8N_PREFLIGHT_ROOT={TMP}"]
    if write:
        env += ["-e", "N8N_PREFLIGHT_ENABLE_WRITE=true"]
    return env + ["--", PY, "-m", "n8n_preflight.server"]


def call(tool: str, **args) -> list[str]:
    out = ["--method", "tools/call", "--tool-name", tool]
    if args:
        out += ["--tool-arg", *[f"{k}={v}" for k, v in args.items()]]
    return out


LIST = ["--method", "tools/list"]
norm = lambda o: o.replace('":', '": ').replace(":  ", ": ")  # noqa: E731  tolerate compact JSON
CLEAN_INLINE = json.dumps(json.loads((FIX / "clean.json").read_text()))

CASES = [
    ("I1", "tools/list, write tools off: 3 read tools", False, LIST,
     lambda o: all(f'"{t}"' in o for t in ("lint_workflow", "summarize_workflow", "list_rules"))
     and "write_sanitized_copy" not in o and '"readOnlyHint": true' in norm(o)),
    ("I2", "lint broken.json profile=run finds the planted failures", False,
     call("lint_workflow", path="broken.json", profile="run"),
     lambda o: all(r in o for r in ("N8P001", "N8P002", "N8P004", "N8P005", "N8P007", "N8P008"))
     and "Did you mean 'Clean lead'" in o and '"passed": false' in norm(o) and "N8P101" not in o),
    ("I3", "lint broken.json profile=share: secret and email found but masked", False,
     call("lint_workflow", path="broken.json", profile="share"),
     lambda o: "N8P101" in o and "N8P103" in o and "N8P104" in o
     and FAKE_BEARER.split()[1] not in o and FAKE_EMAIL not in o),
    ("I4", "lint clean.json profile=template: no findings", False,
     call("lint_workflow", path="clean.json", profile="template"),
     lambda o: '"passed": true' in norm(o) and '"findings": []' in norm(o)),
    ("I5", "lint inline workflow_json", False, call("lint_workflow", workflow_json=CLEAN_INLINE, profile="run"),
     lambda o: '"source": "inline"' in norm(o) and '"passed": true' in norm(o)),
    ("I6", "path outside N8N_PREFLIGHT_ROOT is refused", False,
     call("lint_workflow", path=str(OUTSIDE / "secret.json")),
     lambda o: '"isError": true' in norm(o) and "outside N8N_PREFLIGHT_ROOT" in o),
    ("I7", "../ traversal is refused", False, call("lint_workflow", path="../x.json"),
     lambda o: "outside N8N_PREFLIGHT_ROOT" in o),
    ("I8", "non-.json file is refused", False, call("lint_workflow", path="notes.txt"),
     lambda o: "Only .json files" in o),
    ("I9", "both path and workflow_json is refused", False,
     call("lint_workflow", path="clean.json", workflow_json=CLEAN_INLINE),
     lambda o: "exactly one of" in o),
    ("I10", "invalid profile is rejected by the input schema", False,
     call("lint_workflow", path="clean.json", profile="strict"),
     lambda o: '"isError": true' in norm(o) or "Input validation" in o),
    ("I11", "not a workflow (no nodes) is refused", False, call("lint_workflow", path="not-a-workflow.json"),
     lambda o: "Not an n8n workflow export" in o),
    ("I12", "summarize broken.json", False, call("summarize_workflow", path="broken.json"),
     lambda o: '"slackApi"' in o and "n8n-nodes-base.httpRequest" in o and '"node_count": 7' in norm(o)),
    ("I13", "list_rules category=template", False, call("list_rules", category="template"),
     lambda o: '"count": 4' in norm(o) and "N8P201" in o and "N8P001" not in o),
    ("I14", "write tool is not callable when write tools are off", False,
     call("write_sanitized_copy", path="broken.json", output_path="shared.json", confirm="true"),
     lambda o: "write_sanitized_copy" in o and ("unknown" in o.lower() or "not found" in o.lower())
     and not (TMP / "shared.json").exists()),
    ("W1", "tools/list with N8N_PREFLIGHT_ENABLE_WRITE=true", True, LIST,
     lambda o: '"write_sanitized_copy"' in o and '"readOnlyHint": false' in norm(o)),
    ("W2", "write without confirm returns a preview and writes nothing", True,
     call("write_sanitized_copy", path="broken.json", output_path="shared.json"),
     lambda o: '"written": false' in norm(o) and "removed pinData" in o and not (TMP / "shared.json").exists()),
    ("W3", "write with confirm=true writes the copy", True,
     call("write_sanitized_copy", path="broken.json", output_path="shared.json", confirm="true"),
     lambda o: '"written": true' in norm(o) and (TMP / "shared.json").exists()
     and FAKE_BEARER not in (TMP / "shared.json").read_text() and "pinData" not in (TMP / "shared.json").read_text()),
    ("W4", "write never overwrites an existing file", True,
     call("write_sanitized_copy", path="broken.json", output_path="shared.json", confirm="true"),
     lambda o: "already exists" in o),
    ("W5", "write outside the root is refused", True,
     call("write_sanitized_copy", path="broken.json", output_path=str(OUTSIDE / "x.json"), confirm="true"),
     lambda o: "outside N8N_PREFLIGHT_ROOT" in o and not (OUTSIDE / "x.json").exists()),
    ("W6", "the written copy lints without secret/credential/pinData findings", True,
     call("lint_workflow", path="shared.json", profile="share"),
     lambda o: not any(r in o for r in ("N8P101", "N8P102", "N8P103", "N8P105")) and "N8P104" in o),
]


def main() -> int:
    build_broken(TMP)
    (TMP / "clean.json").write_text((FIX / "clean.json").read_text())
    (TMP / "not-a-workflow.json").write_text('{"name": "x"}')
    (TMP / "notes.txt").write_text("hello")
    (OUTSIDE / "secret.json").write_text('{"nodes": []}')
    LOGS.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, MCP_CATALOG_PATH=str(TMP / ".inspector-catalog.json"))
    env.pop("N8N_PREFLIGHT_ENABLE_WRITE", None)
    rows, raw = [], []
    for cid, desc, write, method, check in CASES:
        cmd = INSPECTOR + ["--cli"] + method + target(write)
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env, cwd=str(OUTSIDE))
        ms = int((time.time() - t0) * 1000)
        out = p.stdout + "\n" + p.stderr
        ok = bool(check(out))
        rows.append((cid, desc, "PASS" if ok else "FAIL", p.returncode, ms))
        raw.append(f"### {cid} {desc}\n$ {redact(shlex.join(cmd))}\nexit={p.returncode} {ms}ms "
                   f"result={'PASS' if ok else 'FAIL'}\n{redact(out.strip())}\n")
    (LOGS / "inspector-stdio.txt").write_text("\n".join(raw))
    passed = sum(r[2] == "PASS" for r in rows)
    lines = ["| # | case | result | exit | ms |", "|---|---|---|---|---|"]
    lines += [f"| {c} | {d} | {r} | {e} | {m} |" for c, d, r, e, m in rows]
    (LOGS / "summary.md.txt").write_text(f"inspector: {redact(shlex.join(INSPECTOR))}\n{passed}/{len(rows)} passed\n\n"
                                         + "\n".join(lines) + "\n")
    print(f"{passed}/{len(rows)} passed")
    for r in rows:
        print(*r[:3], sep="  ")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
