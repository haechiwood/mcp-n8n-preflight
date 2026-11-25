"""Unit tests for the rule engine and the sanitizer (no MCP client needed)."""
from __future__ import annotations

import json

import pytest

from conftest import FAKE_BEARER, FAKE_EMAIL
from n8n_preflight.rules import RULES, lint, sanitize, summarize


def ids(result):
    return {(f["rule"], f["node"]) for f in result["findings"]}


def test_broken_reliability(broken):
    r = lint(broken, "run")
    got = ids(r)
    assert ("N8P001", "Score lead") in got        # $('clean lead') case typo
    assert ("N8P001", "Notify sales") in got      # $node["Score Lead"]
    assert ("N8P002", "New lead") in got          # responseNode without Respond node
    assert ("N8P004", "Clean lead") in got        # {{ }} without '='
    assert ("N8P005", "Send to CRM") in got       # no retry, stop on error
    assert ("N8P006", None) in got                # no error workflow
    assert ("N8P007", "Old step") in got          # orphan
    assert ("N8P008", "Loop Over Items") in got   # loop output empty
    assert ("N8P009", "Notify sales") in got      # disabled
    assert r["passed"] is False
    assert all(f["category"] == "reliability" for f in r["findings"])


def test_case_hint_in_message(broken):
    msgs = [f["message"] for f in lint(broken, "run")["findings"] if f["rule"] == "N8P001"]
    assert any("Did you mean 'Clean lead'" in m for m in msgs)
    assert any("Did you mean 'Score lead'" in m for m in msgs)


def test_broken_sharing_masks_values(broken):
    r = lint(broken, "share")
    got = ids(r)
    for rule, node in [("N8P101", "Send to CRM"), ("N8P102", "Notify sales"), ("N8P103", None),
                       ("N8P104", "Clean lead"), ("N8P104", "Notify sales"), ("N8P105", None)]:
        assert (rule, node) in got, (rule, node)
    dumped = json.dumps(r)
    assert FAKE_BEARER.split()[1] not in dumped     # secret never echoed
    assert FAKE_EMAIL not in dumped                 # email masked
    assert "C0123456789" not in dumped              # channel ID masked


def test_template_profile(broken, clean):
    got = {f["rule"] for f in lint(broken, "template")["findings"]}
    assert {"N8P201", "N8P202", "N8P203"} <= got
    c = lint(clean, "template")
    assert c["passed"] is True
    assert c["counts"] == {"error": 0, "warning": 0, "info": 0}, c["findings"]


def test_clean_has_no_findings_in_any_profile(clean):
    for p in ("run", "share", "template"):
        assert lint(clean, p)["findings"] == [], p


def test_invalid_input():
    with pytest.raises(ValueError):
        lint({"name": "x"}, "run")
    with pytest.raises(ValueError):
        lint({"nodes": []}, "nope")


def test_sanitize_does_not_touch_input(broken):
    before = json.dumps(broken, sort_keys=True)
    new, changes = sanitize(broken)
    assert json.dumps(broken, sort_keys=True) == before
    assert "pinData" not in new and "instanceId" not in new.get("meta", {})
    assert not any("credentials" in n for n in new["nodes"])
    assert FAKE_BEARER not in json.dumps(new)
    assert any("removed pinData" == c for c in changes)
    after = {f["rule"] for f in lint(new, "share")["findings"]}
    assert not after & {"N8P101", "N8P102", "N8P103", "N8P105"}
    assert "N8P104" in after   # emails/IDs are left for a human on purpose


def test_summarize(broken):
    s = summarize(broken)
    assert s["node_count"] == 7
    assert s["triggers"] == [{"name": "New lead", "type": "n8n-nodes-base.webhook"}]
    assert "n8n-nodes-base.httpRequest" in s["outside_systems"]
    assert "n8n-nodes-base.slack" in s["outside_systems"]
    assert s["credential_types"] == ["slackApi"]
    assert s["disabled_nodes"] == ["Notify sales"]
    assert s["has_pinned_data"] is True


def test_rule_catalogue_complete():
    for k, v in RULES.items():
        assert set(v) == {"category", "severity", "title", "why", "fix"}, k
        assert v["severity"] in {"error", "warning", "info"}
