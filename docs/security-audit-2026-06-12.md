# Security audit -- 2026-06-12 (AT-1149)

AT-1133/1135 revised for Python: dependency and secrets audit ahead of the
public spin-off.

## Dependency audit

Ran `pip-audit` (2.10.1) against `mcp-server/requirements.txt`
(`mcp[cli]`, `fastmcp`, `httpx`, `uvicorn`, `starlette`) in the project
virtualenv:

```
python -m pip_audit -r mcp-server/requirements.txt
```

Result: **No known vulnerabilities found.**

## Secrets audit

1. `git log --all --oneline -- '*.env'` and `git log --all --oneline -- '**/*.env'`
   both return empty -- no `.env` file has ever been committed to this repo's
   history.
2. `git ls-files | grep -i '\.env'` returns only the two template files
   (`docker/.env.example`, `mcp-server/litellm.env.example`), both of which
   are documented as templates containing placeholder values only (e.g.
   `CF_API_BASE=http://127.0.0.1:3100/cfproxy/YOUR_ACCOUNT_ID/v1`).
3. `.gitignore` excludes `docker/.env` and `mcp-server/litellm.env`, the two
   real credential files the templates correspond to.

## Conclusion

No remediation required. Dependency set is clean and no credential material
has been committed.
