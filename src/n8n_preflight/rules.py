"""Static checks for exported n8n workflow JSON. Standard library only.

Nothing here runs a workflow, calls n8n, or touches the network. The checks read
the JSON you export from the n8n editor (Download / Ctrl+C) or from
`n8n export:workflow`.

Each finding is a dict:
  {"rule": "N8P001", "severity": "error|warning|info", "category": "...",
   "node": "<node name or null>", "message": "...", "fix": "..."}

Secret values are never returned. Matches are masked to their first 4 characters.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------
RULES: dict[str, dict[str, str]] = {
    # reliability: things that make a workflow fail or misbehave at run time
    "N8P001": {"category": "reliability", "severity": "error",
               "title": "Expression points at a node that does not exist",
               "why": "$('Name') and $node[\"Name\"] are matched by exact, case-sensitive node name. "
                      "A renamed node or a case typo fails at run time with \"Referenced node doesn't exist\".",
               "fix": "Use the node's exact current name, or rename the node back."},
    "N8P002": {"category": "reliability", "severity": "error",
               "title": "Webhook waits for a Respond to Webhook node that is missing",
               "why": "With Respond = 'Using Respond to Webhook Node', a production call fails "
                      "when no Respond to Webhook node runs.",
               "fix": "Add a Respond to Webhook node on every path, or set Respond to 'Immediately' "
                      "or 'When Last Node Finishes'."},
    "N8P003": {"category": "reliability", "severity": "warning",
               "title": "Respond to Webhook node without a webhook that uses it",
               "why": "The node only works when the Webhook trigger is set to respond 'Using Respond to "
                      "Webhook Node'. Otherwise it errors or is ignored.",
               "fix": "Set the Webhook trigger's Respond option to 'Using Respond to Webhook Node', or remove the node."},
    "N8P004": {"category": "reliability", "severity": "warning",
               "title": "{{ }} in a field that is not an expression",
               "why": "In the JSON, expressions start with '='. A value like 'Hello {{ $json.name }}' "
                      "without '=' is sent as literal text, braces included.",
               "fix": "Switch the field to Expression mode in the editor (the stored value then starts with '=')."},
    "N8P005": {"category": "reliability", "severity": "warning",
               "title": "HTTP Request without retry or error handling",
               "why": "One timeout, 429 or 5xx stops the whole execution.",
               "fix": "Turn on Settings > Retry On Fail (for example 3 tries, 2000 ms), and choose an On Error "
                      "behaviour that your workflow handles."},
    "N8P006": {"category": "reliability", "severity": "info",
               "title": "No error workflow set",
               "why": "When a production execution fails, nobody is told.",
               "fix": "Workflow Settings > Error Workflow: pick a workflow that starts with an Error Trigger "
                      "and sends you an alert."},
    "N8P007": {"category": "reliability", "severity": "warning",
               "title": "Node is not connected to anything",
               "why": "A node with no incoming connection never runs (unless it is a trigger).",
               "fix": "Connect it or delete it."},
    "N8P008": {"category": "reliability", "severity": "warning",
               "title": "Loop Over Items: the loop output is not connected",
               "why": "Loop Over Items (Split in Batches v3) sends each batch out of the 'loop' output. "
                      "If nothing is connected there, the items are never processed.",
               "fix": "Connect the 'loop' output to the steps that process a batch, and connect the last of "
                      "those steps back to Loop Over Items."},
    "N8P009": {"category": "reliability", "severity": "info",
               "title": "Disabled node",
               "why": "Disabled nodes pass items through without doing their job. Easy to forget after a test.",
               "fix": "Re-enable it, or delete it if it is no longer needed."},
    # sharing: things to remove before you send the JSON to anyone
    "N8P101": {"category": "sharing", "severity": "error",
               "title": "Secret written into a node parameter",
               "why": "API keys, tokens and passwords in parameters, code or notes travel with the JSON "
                      "to anyone you share it with.",
               "fix": "Move it into an n8n credential, revoke the exposed value, and re-export."},
    "N8P102": {"category": "sharing", "severity": "warning",
               "title": "Credential name and ID included",
               "why": "Exports include each credential's name and ID. Names often identify your "
                      "account or client.",
               "fix": "Remove the 'credentials' blocks before sharing (write_sanitized_copy can do this). "
                      "The receiver selects their own credentials after import."},
    "N8P103": {"category": "sharing", "severity": "warning",
               "title": "Pinned execution data included",
               "why": "pinData holds real run output: emails, names, order data.",
               "fix": "Unpin data in the editor, or remove 'pinData' from the JSON."},
    "N8P104": {"category": "sharing", "severity": "warning",
               "title": "Personal or private identifier in a parameter",
               "why": "Email addresses, spreadsheet IDs, chat IDs and channel IDs point at your own "
                      "accounts and data.",
               "fix": "Replace with a clear placeholder, and explain in a note how to set it."},
    "N8P105": {"category": "sharing", "severity": "info",
               "title": "Instance ID in workflow metadata",
               "why": "meta.instanceId identifies the n8n instance the workflow came from.",
               "fix": "Remove meta.instanceId before sharing (write_sanitized_copy does this)."},
    # template: n8n Creator Hub readiness (https://docs.n8n.io/contribute/create-templates/)
    "N8P201": {"category": "template", "severity": "warning",
               "title": "No overview sticky note",
               "why": "Creator Hub templates need one main overview note with '### How it works' and "
                      "'### Setup', 100 to 300 words.",
               "fix": "Add a yellow sticky note in the top-left with those headings."},
    "N8P202": {"category": "template", "severity": "warning",
               "title": "No section notes",
               "why": "Workflows with four or more nodes need section notes that group related nodes.",
               "fix": "Add short notes with a '## Heading' (under 50 words) over each group of nodes."},
    "N8P203": {"category": "template", "severity": "info",
               "title": "Default node name",
               "why": "Names like 'HTTP Request1' or 'Code' do not say what the step does.",
               "fix": "Rename the node to describe its purpose, for example 'Find existing contact'."},
    "N8P204": {"category": "template", "severity": "warning",
               "title": "Overview note length outside 100 to 300 words",
               "why": "The Creator Hub sticky note guideline asks for 100 to 300 words.",
               "fix": "Shorten or extend the overview note."},
}

CATEGORIES_BY_PROFILE = {
    "run": ("reliability",),
    "share": ("reliability", "sharing"),
    "template": ("reliability", "sharing", "template"),
}

# ---------------------------------------------------------------------------
# Node type helpers
# ---------------------------------------------------------------------------
STICKY = "n8n-nodes-base.stickyNote"
WEBHOOK = "n8n-nodes-base.webhook"
RESPOND = "n8n-nodes-base.respondToWebhook"
HTTP = "n8n-nodes-base.httpRequest"
LOOP = "n8n-nodes-base.splitInBatches"
CODE_TYPES = {"n8n-nodes-base.code", "n8n-nodes-base.function", "n8n-nodes-base.functionItem"}
TRIGGER_TYPES = {WEBHOOK, "n8n-nodes-base.start", "n8n-nodes-base.cron", "n8n-nodes-base.interval",
                 "n8n-nodes-base.formTrigger", "@n8n/n8n-nodes-langchain.chatTrigger",
                 "@n8n/n8n-nodes-langchain.mcpTrigger"}
# Types that only move data around inside n8n. Everything else may reach an outside system.
LOCAL_TYPES = {STICKY, "n8n-nodes-base.set", "n8n-nodes-base.if", "n8n-nodes-base.switch",
               "n8n-nodes-base.merge", "n8n-nodes-base.noOp", "n8n-nodes-base.filter",
               "n8n-nodes-base.sort", "n8n-nodes-base.limit", "n8n-nodes-base.aggregate",
               "n8n-nodes-base.splitOut", "n8n-nodes-base.removeDuplicates", "n8n-nodes-base.dateTime",
               "n8n-nodes-base.crypto", "n8n-nodes-base.wait", "n8n-nodes-base.stopAndError",
               "n8n-nodes-base.executionData", "n8n-nodes-base.summarize", "n8n-nodes-base.compareDatasets",
               "n8n-nodes-base.renameKeys", "n8n-nodes-base.itemLists", "n8n-nodes-base.html",
               "n8n-nodes-base.xml", "n8n-nodes-base.markdown", "n8n-nodes-base.convertToFile",
               "n8n-nodes-base.extractFromFile", "n8n-nodes-base.manualTrigger", "n8n-nodes-base.errorTrigger",
               "n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.executeWorkflowTrigger", RESPOND, LOOP,
               WEBHOOK, "n8n-nodes-base.formTrigger", "n8n-nodes-base.form"} | CODE_TYPES
DEFAULT_NAME_RE = re.compile(
    r"^(HTTP Request|Code|If|Switch|Edit Fields|Set|Merge|Webhook|No Operation, do nothing|Function|"
    r"Function Item|Filter|Split Out|Aggregate|Loop Over Items|Split In Batches|Wait|Respond to Webhook|"
    r"Schedule Trigger|Execute Workflow|Basic LLM Chain|AI Agent|OpenAI Chat Model|Anthropic Chat Model|"
    r"Gmail|Slack|Google Sheets|Telegram|Discord|Remove Duplicates|Date & Time|Crypto|Sort|Limit)( ?\d+)?$")


def is_trigger(node: dict) -> bool:
    t = node.get("type", "")
    return t in TRIGGER_TYPES or t.endswith("Trigger") or t.endswith(".trigger")


def is_ai_subnode(node: dict, connections: dict) -> bool:
    """AI sub-nodes (models, memory, tools, parsers) connect out through ai_* ports, not 'main'."""
    outs = connections.get(node.get("name", ""), {})
    return any(k.startswith("ai_") and any(v) for k, v in outs.items())


# ---------------------------------------------------------------------------
# Walk all string values of a node's parameters
# ---------------------------------------------------------------------------
def iter_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from iter_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from iter_strings(v, f"{path}[{i}]")


# $('Name'), $("Name"), $node["Name"], $node['Name'], $items("Name")
REF_RES = [
    re.compile(r"""\$\(\s*(['"])((?:\\.|(?!\1).)+)\1\s*\)"""),
    re.compile(r"""\$node\[\s*(['"])((?:\\.|(?!\1).)+)\1\s*\]"""),
    re.compile(r"""\$items\(\s*(['"])((?:\\.|(?!\1).)+)\1"""),
]

SECRET_RES = [
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")),
    ("google_key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("slack_token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("stripe_key", re.compile(r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("bearer_literal", re.compile(r"Bearer\s+(?!\{\{|=)[A-Za-z0-9._~+/=-]{16,}")),
    ("basic_auth_url", re.compile(r"https?://[^/\s:@\"']+:[^/\s@\"']+@")),
    ("token_in_url", re.compile(
        r"[?&](?:api[_-]?key|apikey|access_token|token|key|secret)=(?!\{\{)[A-Za-z0-9._~-]{12,}", re.I)),
]
SECRET_HEADER_NAMES = re.compile(r"^(authorization|x-api-key|api[_-]?key|apikey|token|access[_-]?token|secret)$", re.I)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
PLACEHOLDER_EMAIL_DOMAINS = re.compile(r"@(example\.(com|org|net)|[a-z0-9-]+\.example|test\.com|domain\.com|"
                                       r"yourcompany\.com|your-domain\.com|company\.com)$", re.I)
PRIVATE_ID_KEYS = re.compile(r"(documentId|sheetId|spreadsheetId|chatId|channelId|channel|folderId|"
                             r"databaseId|baseId|tableId|calendarId|listId|boardId|pageId)$", re.I)


def mask(s: str) -> str:
    s = s.strip()
    return (s[:4] + "***") if len(s) > 4 else "***"


def _finding(rule: str, node: str | None, message: str) -> dict:
    r = RULES[rule]
    return {"rule": rule, "severity": r["severity"], "category": r["category"], "node": node,
            "message": message, "fix": r["fix"]}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _incoming_any(connections: dict) -> set[str]:
    targets: set[str] = set()
    for _src, outs in connections.items():
        for _port, lists in (outs or {}).items():
            for lst in lists or []:
                for c in lst or []:
                    if isinstance(c, dict) and c.get("node"):
                        targets.add(c["node"])
    return targets


def check_reliability(wf: dict) -> list[dict]:
    out: list[dict] = []
    nodes = [n for n in wf.get("nodes", []) if isinstance(n, dict)]
    conns = wf.get("connections") or {}
    names = {n.get("name") for n in nodes}
    lower = {}
    for nm in names:
        if isinstance(nm, str):
            lower.setdefault(nm.lower(), nm)

    # N8P001 broken node references
    for n in nodes:
        if n.get("type") == STICKY:
            continue
        seen: set[str] = set()
        for _path, s in iter_strings(n.get("parameters", {})):
            for rx in REF_RES:
                for m in rx.finditer(s):
                    ref = m.group(2).replace("\\'", "'").replace('\\"', '"')
                    if ref in names or ref in seen:
                        continue
                    seen.add(ref)
                    hint = lower.get(ref.lower())
                    msg = f"References node '{ref}', which is not in this workflow."
                    if hint:
                        msg += f" Did you mean '{hint}'? Names are case-sensitive."
                    out.append(_finding("N8P001", n.get("name"), msg))

    # N8P002 / N8P003 webhook response mode
    respond_nodes = [n for n in nodes if n.get("type") == RESPOND and not n.get("disabled")]
    hooks = [n for n in nodes if n.get("type") == WEBHOOK and not n.get("disabled")]
    hooks_waiting = [n for n in hooks if (n.get("parameters") or {}).get("responseMode") == "responseNode"]
    for h in hooks_waiting:
        if not respond_nodes:
            out.append(_finding("N8P002", h.get("name"),
                                "Respond is set to 'Using Respond to Webhook Node', but the workflow has no "
                                "enabled Respond to Webhook node."))
    if respond_nodes and hooks and not hooks_waiting:
        for r in respond_nodes:
            out.append(_finding("N8P003", r.get("name"),
                                "No Webhook trigger here is set to respond 'Using Respond to Webhook Node'."))

    # N8P004 {{ }} without '='
    for n in nodes:
        if n.get("type") == STICKY or n.get("type") in CODE_TYPES:
            continue
        for path, s in iter_strings(n.get("parameters", {})):
            if "{{" in s and "}}" in s and not s.startswith("=") and re.search(r"\{\{\s*\$", s):
                out.append(_finding("N8P004", n.get("name"),
                                    f"Parameter '{path}' contains '{{{{ $... }}}}' but is stored as fixed text."))
                break

    # N8P005 HTTP Request without retry / error handling
    for n in nodes:
        if n.get("type") != HTTP or n.get("disabled"):
            continue
        if not n.get("retryOnFail") and n.get("onError") in (None, "stopWorkflow"):
            out.append(_finding("N8P005", n.get("name"), "Retry On Fail is off and On Error is 'Stop Workflow'."))

    # N8P006 error workflow
    has_prod_trigger = any(is_trigger(n) and n.get("type") not in (
        "n8n-nodes-base.manualTrigger", "n8n-nodes-base.errorTrigger", "n8n-nodes-base.executeWorkflowTrigger")
        for n in nodes if not n.get("disabled"))
    if has_prod_trigger and not (wf.get("settings") or {}).get("errorWorkflow"):
        out.append(_finding("N8P006", None, "settings.errorWorkflow is empty."))

    # N8P007 orphan nodes
    incoming = _incoming_any(conns)
    for n in nodes:
        if n.get("type") == STICKY or is_trigger(n) or is_ai_subnode(n, conns):
            continue
        if n.get("name") not in incoming:
            out.append(_finding("N8P007", n.get("name"), "No connection leads into this node."))

    # N8P008 loop output
    for n in nodes:
        if n.get("type") != LOOP or float(n.get("typeVersion") or 1) < 3:
            continue
        main = (conns.get(n.get("name"), {}) or {}).get("main") or []
        loop_out = main[1] if len(main) > 1 else []
        if not loop_out:
            out.append(_finding("N8P008", n.get("name"), "Output 'loop' (the second output) has no connection."))

    # N8P009 disabled
    for n in nodes:
        if n.get("disabled") and n.get("type") != STICKY:
            out.append(_finding("N8P009", n.get("name"), "This node is disabled."))
    return out


def check_sharing(wf: dict) -> list[dict]:
    out: list[dict] = []
    nodes = [n for n in wf.get("nodes", []) if isinstance(n, dict)]
    for n in nodes:
        name = n.get("name")
        reported: set[str] = set()
        params = n.get("parameters", {})
        # N8P101 secrets in any string (code and sticky notes included)
        for path, s in iter_strings(params):
            for kind, rx in SECRET_RES:
                m = rx.search(s)
                if m and kind not in reported:
                    reported.add(kind)
                    out.append(_finding("N8P101", name, f"{kind} in '{path}': {mask(m.group(0))}"))
        # header/query pairs: a name like Authorization next to a literal (non-expression) value
        for path, obj in _iter_dicts(params):
            nm, val = obj.get("name"), obj.get("value")
            if (isinstance(nm, str) and SECRET_HEADER_NAMES.match(nm) and isinstance(val, str)
                    and len(val) >= 8 and not val.startswith(("=", "<")) and "auth_param" not in reported):
                reported.add("auth_param")
                out.append(_finding("N8P101", name, f"literal value for '{nm}' in '{path}': {mask(val)}"))
        # N8P104 emails and private resource IDs
        for path, s in iter_strings(params):
            if n.get("type") == STICKY:
                break
            for m in EMAIL_RE.finditer(s):
                if not PLACEHOLDER_EMAIL_DOMAINS.search(m.group(0)):
                    out.append(_finding("N8P104", name, f"email address in '{path}': {mask(m.group(0))}"))
                    break
        for path, obj in _iter_dicts(params):
            for k, v in obj.items():
                if not PRIVATE_ID_KEYS.search(k):
                    continue
                val = v.get("value") if isinstance(v, dict) and "__rl" in v else v
                if (isinstance(val, str) and val and not val.startswith("=") and len(val) >= 6
                        and not re.match(r"^(YOUR|REPLACE|<|\{\{|example|placeholder)", val, re.I)):
                    out.append(_finding("N8P104", name, f"'{k}' has a fixed value: {mask(val)}"))
        # N8P102 credentials
        creds = n.get("credentials") or {}
        if creds:
            types = ", ".join(sorted(creds))
            out.append(_finding("N8P102", name, f"credentials block for: {types}"))
    if wf.get("pinData"):
        out.append(_finding("N8P103", None, f"pinData for {len(wf['pinData'])} node(s): "
                            + ", ".join(sorted(wf["pinData"]))[:200]))
    if (wf.get("meta") or {}).get("instanceId"):
        out.append(_finding("N8P105", None, "meta.instanceId is set."))
    return out


def _iter_dicts(value: Any, path: str = "") -> Iterable[tuple[str, dict]]:
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items():
            yield from _iter_dicts(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_dicts(v, f"{path}[{i}]")


def sticky_notes(wf: dict) -> list[dict]:
    return [n for n in wf.get("nodes", []) if isinstance(n, dict) and n.get("type") == STICKY]


def check_template(wf: dict) -> list[dict]:
    out: list[dict] = []
    nodes = [n for n in wf.get("nodes", []) if isinstance(n, dict)]
    work = [n for n in nodes if n.get("type") != STICKY]
    notes = sticky_notes(wf)
    overview = [s for s in notes if "### how it works" in str((s.get("parameters") or {}).get("content", "")).lower()
                and "### setup" in str((s.get("parameters") or {}).get("content", "")).lower()]
    if not overview:
        out.append(_finding("N8P201", None, f"{len(notes)} sticky note(s), none with '### How it works' and '### Setup'."))
    else:
        words = len(re.findall(r"[A-Za-z0-9'’-]+", str(overview[0]["parameters"].get("content", ""))))
        if not 100 <= words <= 300:
            out.append(_finding("N8P204", overview[0].get("name"), f"Overview note has about {words} words."))
    if len(work) >= 4 and len(notes) - len(overview) < 1:
        out.append(_finding("N8P202", None, f"{len(work)} nodes and no section notes."))
    for n in work:
        if DEFAULT_NAME_RE.match(str(n.get("name", ""))):
            out.append(_finding("N8P203", n.get("name"), "Default node name."))
    return out


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def lint(wf: dict, profile: str = "share") -> dict:
    if profile not in CATEGORIES_BY_PROFILE:
        raise ValueError(f"profile must be one of {sorted(CATEGORIES_BY_PROFILE)}")
    if not isinstance(wf, dict) or not isinstance(wf.get("nodes"), list):
        raise ValueError("Not an n8n workflow: expected an object with a 'nodes' list.")
    cats = CATEGORIES_BY_PROFILE[profile]
    findings: list[dict] = []
    if "reliability" in cats:
        findings += check_reliability(wf)
    if "sharing" in cats:
        findings += check_sharing(wf)
    if "template" in cats:
        findings += check_template(wf)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["rule"], f["node"] or ""))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("error", "warning", "info")}
    return {"workflow": wf.get("name"), "profile": profile, "checked_categories": list(cats),
            "passed": counts["error"] == 0, "counts": counts, "findings": findings}


def summarize(wf: dict) -> dict:
    if not isinstance(wf, dict) or not isinstance(wf.get("nodes"), list):
        raise ValueError("Not an n8n workflow: expected an object with a 'nodes' list.")
    nodes = [n for n in wf["nodes"] if isinstance(n, dict)]
    conns = wf.get("connections") or {}
    work = [n for n in nodes if n.get("type") != STICKY]
    return {
        "name": wf.get("name"),
        "node_count": len(work),
        "sticky_notes": len(nodes) - len(work),
        "triggers": [{"name": n.get("name"), "type": n.get("type")} for n in work if is_trigger(n)],
        "outside_systems": sorted({n.get("type") for n in work
                                   if n.get("type") not in LOCAL_TYPES and not is_trigger(n)}),
        "ai_nodes": sorted({n.get("name") for n in work if "langchain" in str(n.get("type"))}),
        "credential_types": sorted({t for n in work for t in (n.get("credentials") or {})}),
        "disabled_nodes": [n.get("name") for n in work if n.get("disabled")],
        "error_workflow_set": bool((wf.get("settings") or {}).get("errorWorkflow")),
        "has_pinned_data": bool(wf.get("pinData")),
        "connections_from": len(conns),
    }


def sanitize(wf: dict) -> tuple[dict, list[str]]:
    """Return a copy for sharing and the list of changes. Never touches the input dict."""
    import copy

    new = copy.deepcopy(wf)
    changes: list[str] = []
    if new.pop("pinData", None):
        changes.append("removed pinData")
    meta = new.get("meta") or {}
    if meta.pop("instanceId", None):
        changes.append("removed meta.instanceId")
    for key in ("id", "versionId", "shared", "activeVersionId"):
        if new.pop(key, None) is not None:
            changes.append(f"removed top-level '{key}'")
    if new.get("active"):
        new["active"] = False
        changes.append("set active=false")
    for n in new.get("nodes", []):
        if not isinstance(n, dict):
            continue
        if n.pop("credentials", None):
            changes.append(f"removed credentials from '{n.get('name')}'")
        params = n.get("parameters")
        if params is not None:
            n["parameters"], hits = _redact(params)
            for h in hits:
                changes.append(f"replaced a {h} in '{n.get('name')}' with <REPLACE_ME>")
    return new, changes


def _redact(value: Any) -> tuple[Any, list[str]]:
    hits: list[str] = []

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            s = v
            for kind, rx in SECRET_RES:
                if rx.search(s):
                    s = rx.sub("<REPLACE_ME>", s)
                    hits.append(kind)
            return s
        if isinstance(v, dict):
            d = {k: walk(x) for k, x in v.items()}
            nm, val = d.get("name"), d.get("value")
            if (isinstance(nm, str) and SECRET_HEADER_NAMES.match(nm) and isinstance(val, str)
                    and len(val) >= 8 and not val.startswith("=") and val != "<REPLACE_ME>"):
                d["value"] = "<REPLACE_ME>"
                hits.append(f"'{nm}' value")
            return d
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value), hits
