# Odysseus workspace-registration preset template

AT-1222. Odysseus has no native "registered repos" concept (no
Workspace/Project model in `core/`). Verified 2026-06-18: listing the repo
paths in a preset's `system_prompt` field works immediately with zero new
code, because Skein MCP's file/shell tools (`fs_read_file`, `fs_write_file`,
`run_shell`, `list_directory`) all resolve absolute paths as-is (`_resolve`
in `local-mcp.py`) -- there is no sandbox restricting them to one repo.

Without this, the model only finds the right repo if you spell out the path
in chat. With it, you can say "check git status in skein-toolkit" and it
resolves the path itself.

## Template

Paste this into a preset's system prompt (Odysseus Settings -> Presets):

```
You have file and shell access to these repos via the local-devtools MCP
tools (fs_read_file, fs_write_file, run_shell, list_directory), using
absolute paths -- there is no path restriction, any absolute path works:

- c:\Users\jakeh\source\repos\Electron-Splines
  Geometry editor (TypeScript/Electron). The AT/OQ task queue and OQ ledger
  live here: architecture-docs/global/ai-task-queue.md and
  architecture-docs/global/architect-open-questions.md.

- c:\Users\jakeh\source\repos\skein-toolkit
  AI ops tooling: the Skein MCP server itself (mcp-server/local-mcp.py),
  LiteLLM config, devserver scripts, and cross-project specs/docs under
  foundation/SR-1.4-ai-guidance/.

- c:\Users\jakeh\source\repos\odysseus
  This chat application (Python/FastAPI + static HTML/JS frontend).

When asked to do something involving one of these repos, resolve the path
yourself rather than asking for it spelled out, unless genuinely ambiguous
which repo is meant.
```

## When this stops being enough

If listing 3+ repos by hand in every preset becomes real friction (more
repos, multiple presets needing the same list, the list changing often),
the next step is a small dedicated config (e.g. a `workspaces.json` read at
startup and injected into context) instead of a copy-pasted preset block --
see `odysseus-agentic-dispatch-architecture.md` §6. Not built yet because
the manual version above has cost approximately zero so far.
