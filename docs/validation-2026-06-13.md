# Docker Compose end-to-end validation (AT-1146)

**Date:** 2026-06-13
**Environment:** fresh `git clone` of `https://github.com/Hendo52/skein-toolkit.git`
into a scratch directory outside any Electron-Splines checkout (`/tmp/skein-toolkit-validation`),
Docker Desktop 29.5.2 on Windows.

## Steps run

1. `git clone https://github.com/Hendo52/skein-toolkit.git` into a clean
   scratch directory.
2. `cp docker/.env.example docker/.env` (per README "Quick start (Docker)" --
   left at placeholder values, no real API keys needed for this validation).
3. `docker compose config` -- **failed** on the first attempt before step 2
   because `docker/.env` doesn't exist in a fresh clone (gitignored by
   design, matches `litellm`'s `env_file:` requirement). This is expected and
   already documented in the README; not a bug.
4. `docker compose build mcp-server` -- **failed**:
   ```
   invalid tag "{{IMAGE_NAME}}/mcp-server:{{TAG}}": invalid reference format
   ```
   `docker-compose.yml` shipped an unsubstituted template placeholder for the
   `mcp-server` image tag with no substitution step anywhere in the repo
   (`grep -rn "IMAGE_NAME"` found only this one line). **Fixed**: changed
   `image: "{{IMAGE_NAME}}/mcp-server:{{TAG}}"` to
   `image: "skein-toolkit/mcp-server:dev"` in `docker-compose.yml` (commit
   in this same change).
5. `docker compose up --build -d` -- succeeded after the fix. Both
   containers reached `Up`:
   - `llm-toolkit-mcp-server` (image `skein-toolkit/mcp-server:dev`,
     port 3100) -- logs show `Uvicorn running on http://127.0.0.1:3100`,
     `Application startup complete.`
   - `llm-toolkit-litellm` (image `ghcr.io/berriai/litellm:main-latest`,
     port 4000) -- logs show the full model list loaded and
     `Uvicorn running on http://0.0.0.0:4000`.
6. `curl http://127.0.0.1:3100/sse` -- connection accepted (SSE stream opens,
   does not close, as expected for `mcp.server.fastmcp.FastMCP`'s SSE
   transport).
7. `curl http://127.0.0.1:4000/health/readiness` -- `200`.
8. AT-1145 test suite inside the running `mcp-server` container: the
   production image (by design, see "Findings" below) does not include
   `mcp-server/tests/`, so the test tree was copied in with
   `docker cp mcp-server/tests/. llm-toolkit-mcp-server:/app/mcp-server/tests/`
   and run via `docker compose exec mcp-server python -m unittest discover
   tests -v`:
   ```
   Ran 57 tests in 0.009s
   OK
   ```
   All 57 cases pass inside the container's Python 3.12 environment, matching
   the local/CI results from AT-1145.
9. `docker compose down -v` -- clean teardown, no leftover containers/networks.

## Findings

- **Fixed (this change):** `docker-compose.yml`'s `mcp-server.image` was an
  unsubstituted `{{IMAGE_NAME}}/mcp-server:{{TAG}}` placeholder that breaks
  `docker compose build`/`up` in any clean checkout. Replaced with a static
  `skein-toolkit/mcp-server:dev` tag. No templating/substitution mechanism
  existed elsewhere in the repo, so this was dead template syntax left over
  from spin-off, not a configured feature.
- **By design, not a bug:** `mcp-server/Dockerfile` only `COPY`s
  `local-mcp.py`/`devserver-mcp.py` into the image -- the test suite is
  intentionally excluded from the shipped image to keep it lean. Verified by
  copying the test tree into the running container for this validation
  (step 8); CI (`ci.yml`) separately runs the same suite outside Docker on
  every push/PR.
- **Pre-existing, documented:** `docker/.env` must be created from
  `docker/.env.example` before `docker compose up` -- already covered by the
  README's "Quick start (Docker)" section; placeholder values are sufficient
  for `mcp-server` and for `litellm` to start (no live model calls were
  exercised in this validation).
- **No Electron-Splines files were touched.** The clone and all commands ran
  in `/tmp/skein-toolkit-validation`, fully isolated from this checkout.

## Result

`docker compose up --build` now succeeds end-to-end from a clean clone;
`mcp-server` and `litellm` both come up healthy; the AT-1145 test suite (57
cases) passes inside the container's runtime environment. AT-1146 exit
evidence met.
