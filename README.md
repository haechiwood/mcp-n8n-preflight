# n8n Preflight (MCP server)

<!-- mcp-name: io.github.haechiwood/n8n-preflight -->

[![haechiwood/mcp-n8n-preflight MCP server](https://glama.ai/mcp/servers/haechiwood/mcp-n8n-preflight/badges/score.svg)](https://glama.ai/mcp/servers/haechiwood/mcp-n8n-preflight)

Check an exported n8n workflow **before** you import it, share it, or submit it as a template.
Ask Claude "is this workflow safe to share?" or "why does this workflow fail?" and it can read the
JSON file and get a list of concrete problems, each with a fix.

- **Offline and read-only by default.** It reads `.json` files from one folder. It never runs a workflow,
  never connects to your n8n instance, and makes no network requests. No API key needed.
- **Finds failures that only show up at run time**: `$('node name')` typos, a webhook waiting for a Respond
  node that is missing, `{{ }}` in a field that is not in expression mode, an unconnected Loop Over Items
  output, HTTP calls with no retry.
- **Finds what you should not share**: literal API keys and Bearer tokens, credential names and IDs,
  pinned execution data, email addresses, spreadsheet and channel IDs, the instance ID.
- **Checks n8n Creator Hub template basics**: overview sticky note with `### How it works` / `### Setup`
  (100 to 300 words), section notes, default node names
  ([n8n guideline](https://docs.n8n.io/contribute/create-templates/sticky-note-guidelines)).

Not affiliated with n8n GmbH. "n8n" is used only to say which file format this tool reads.

## Tools

| Tool | Type | What it does |
|---|---|---|
| `lint_workflow` | read | Findings for one workflow file or inline JSON. `profile`: `run` (reliability), `share` (default: reliability + sharing), `template` (all, including Creator Hub checks). Secrets and emails are masked in the output |
| `summarize_workflow` | read | Triggers, node count, outside systems the workflow calls, AI nodes, credential types (types only), disabled nodes |
| `list_rules` | read | Every rule with why it matters and how to fix it |
| `write_sanitized_copy` | **write** | **Not registered** unless `N8N_PREFLIGHT_ENABLE_WRITE=true`. Without `confirm=true` it returns a preview of the changes and writes nothing. With `confirm=true` it writes a new file (never overwrites) without pinned data, credentials, instance ID and literal secrets |

## Rules

| ID | Severity | Checks |
|---|---|---|
| N8P001 | error | Expression points at a node that does not exist (suggests the right case) |
| N8P002 | error | Webhook set to respond "Using Respond to Webhook Node" but there is none |
| N8P003 | warning | Respond to Webhook node but no webhook uses that mode |
| N8P004 | warning | `{{ $... }}` stored as fixed text (missing expression `=`) |
| N8P005 | warning | HTTP Request with Retry On Fail off and On Error = stop |
| N8P006 | info | No error workflow set |
| N8P007 | warning | Node with no incoming connection (not a trigger or AI sub-node) |
| N8P008 | warning | Loop Over Items (v3) with the `loop` output unconnected |
| N8P009 | info | Disabled node |
| N8P101 | error | Literal secret in a parameter, code or note (OpenAI, Anthropic, Google, Slack, GitHub, Stripe, AWS keys, JWT, Bearer, basic-auth URL, key in URL, Authorization header) |
| N8P102 | warning | Credential name and ID included |
| N8P103 | warning | Pinned execution data included |
| N8P104 | warning | Email address or fixed spreadsheet / chat / channel / folder ID |
| N8P105 | info | `meta.instanceId` present |
| N8P201 | warning | No overview sticky note (`### How it works` + `### Setup`) |
| N8P202 | warning | Four or more nodes and no section notes |
| N8P203 | info | Default node name such as `HTTP Request1` |
| N8P204 | warning | Overview note outside 100 to 300 words |

These are static checks. A clean result does not prove a workflow works; only running it with real input does.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/) (or pip).

```bash
uvx mcp-n8n-preflight                                                             # from PyPI
docker run -i --rm -v "$PWD:/work:ro" ghcr.io/haechiwood/mcp-n8n-preflight:0.1.2   # Docker, reads /work
```

Or `pip install mcp-n8n-preflight`.

### Claude Desktop

Settings > Developer > Edit Config, then add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "n8n-preflight": {
      "command": "uvx",
      "args": ["mcp-n8n-preflight"],
      "env": {
        "N8N_PREFLIGHT_ROOT": "/path/to/your/n8n-exports"
      }
    }
  }
}
```

Restart Claude Desktop. Use an absolute path for `N8N_PREFLIGHT_ROOT`. Claude Desktop may not find `uvx`
if it is not on its PATH; then put the full path from `which uvx` in `command`.

### Claude Code

```bash
claude mcp add n8n-preflight -e N8N_PREFLIGHT_ROOT="$PWD" -- uvx mcp-n8n-preflight
claude mcp list          # should show: n8n-preflight ... Connected
```

To allow the write tool, add `-e N8N_PREFLIGHT_ENABLE_WRITE=true`.

### Without an MCP client (CI, pre-commit)

```bash
uvx --from mcp-n8n-preflight n8n-preflight lint my-workflow.json --profile share
# exit 0 = no errors, 1 = errors found, 2 = could not read the file
```

### Example prompts

- "Lint `invoice-sync.json` and explain the errors in plain English."
- "Is `lead-intake.json` safe to post in the n8n forum? Use the share profile."
- "Check `my-template.json` against the template profile before I submit it to the Creator Hub."

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `N8N_PREFLIGHT_ROOT` | current working directory | The only folder the server reads from and writes copies into. Paths outside it (including `../`) are refused. Only `.json`, max 5 MB |
| `N8N_PREFLIGHT_ENABLE_WRITE` | off | `true` registers `write_sanitized_copy` |

No API keys are used. If you fork this to call the n8n API, read keys from environment variables only,
never from tool arguments, and keep them out of logs and error messages.

## Security notes

- **Read-only by default.** The write tool does not exist unless you turn it on, and even then it needs a
  preview call and a second call with `confirm=true`. The server enforces this; client-side approval prompts
  are a second layer, not a replacement. It never overwrites a file.
- **Folder sandbox.** Every path is resolved and must stay inside `N8N_PREFLIGHT_ROOT`.
- **No network, no execution.** The server only parses JSON. It does not run Code node JavaScript.
- **Secrets are masked.** Findings show at most the first 4 characters of a matched secret or email.
- **Prompt injection.** Node names, sticky notes and parameter text come from whoever built the workflow.
  The server tells the client to treat them as data, but a model can still be misled by a crafted file.
  Review findings before acting on them, and keep the write tool off unless you need it.
- `write_sanitized_copy` does not remove emails or IDs inside text. Run `lint_workflow` on the copy and
  replace what is left by hand.

## Tests

```bash
uv venv && uv pip install -e ".[test]"
pytest -q                                   # 9 unit tests (rules, masking, sanitizer)
python tests/run_inspector.py               # 20 end-to-end cases through the official MCP Inspector CLI
```

Latest run (2026-11-26, version 0.1.2, Python 3.12.11, `mcp` 2.3.0, MCP Inspector CLI 2.16.0): **9/9 pytest, 20/20 Inspector cases**
(tool list with and without the write tool, planted failures found, secrets masked, path traversal refused,
preview-then-confirm, no overwrite). Logs: [`tests/logs/summary.md.txt`](tests/logs/summary.md.txt),
[`tests/logs/inspector-stdio.txt`](tests/logs/inspector-stdio.txt). Claude Code 2.1.332 connected over stdio to 0.1.1
(local path and `uvx --from`), see [`tests/logs/claude-code-connect.txt`](tests/logs/claude-code-connect.txt).
Not tested: Claude Desktop, Windows.

Test fixtures build their fake secrets at run time, so this repository holds no secret-looking strings.

## How this was built

AI coding agents wrote the code, tests and this README. Every release must pass the test suite above
before it is published, and the maintainer is accountable for it.

## License

MIT. See [LICENSE](LICENSE).

---

Need a custom MCP server for your API? Hire me on Fiverr: https://www.fiverr.com/haechiwood/build-a-custom-mcp-server-that-connects-your-api-to-claude-and-ai-agents?utm_source=github&utm_medium=readme&utm_campaign=mcp-n8n-preflight
