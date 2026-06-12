# Contributing

This repo is a standalone clone of the AI development toolchain originally
built inside Electron-Splines. It's early-stage (Phase 1 of
`planning_document.md`'s migration plan) -- expect rough edges.

## Code style

- Python: follow the existing style in `mcp-server/local-mcp.py` (plain
  functions, `os.environ.get("VAR", default)` for configuration, no new
  hardcoded absolute paths).
- PowerShell: scripts resolve their own location via `$PSScriptRoot` /
  `Split-Path -Parent $PSScriptRoot` -- don't hardcode drive letters or
  usernames.

## First-class scenarios, not fallbacks

Every reachable code path -- including alternative configurations like "the
OQ ledger path doesn't exist" -- should be a named, observable, tested
scenario: log what happened (`print(..., file=sys.stderr)` at minimum), don't
silently swallow errors. This mirrors the parent project's "First-Class
Scenarios" policy and is the main reason the orchestrator's bounded-ambiguity
paths are as verbose as they are.

## Testing

There is no test suite in this repo yet (tests live in the source repo's
`scripts/tests/`, e.g. `test_local_mcp_validator.py`,
`test_local_mcp_orchestrator_resume.py`). Porting that suite is part of
AT-1125/1126.

## Reporting issues / proposing changes

Open an issue or PR against this repo. For changes to the orchestrator's
governance integrations (OQ ledger, task queue), note that the default
behavior must remain safe for repos that don't have an
`architecture-docs/global/architect-open-questions.md`-style ledger --
see `CF_PROXY_OQ_LEDGER_PATH` in the README.

## License

See `LICENSE`. Licensing terms for external contributions to this standalone
repo (as distinct from the proprietary Electron-Splines source repo) have not
yet been finalized by the project owners -- do not assume MIT/Apache-style
terms until `LICENSE` is updated to say so.
