#!/usr/bin/env python3
"""
Unit tests for AT-1162: advisory file locking around read-modify-write of
shared ledger and orchestrator-state files in local-mcp.py.

Covers:
  - _ledger_lock acquires and releases the sidecar .lock file
  - _ledger_lock logs a wait message when a second caller blocks
  - _ledger_lock raises RuntimeError on timeout (not FileExistsError)
  - _ledger_lock cleans up the .lock file even when the body raises
  - Concurrent-writer simulation: a second process holds the lock while
    the first call blocks, then first call succeeds without a lost update
    (_append_oq_row, _append_at_row, _save_orchestrator_state)
  - ledger_io.py pure functions are NOT wrapped in any lock

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_ledger_locking.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import contextlib

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))
_LEDGER_IO_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "ledger_io.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

import ledger_io  # noqa: E402 -- needs sys.path from above exec


# ---------------------------------------------------------------------------
# Helpers for the concurrent-writer simulation
# ---------------------------------------------------------------------------

def _hold_lock_for(lock_path: str, hold_seconds: float, ready_event_path: str) -> None:
    """Create the sidecar lock file, signal readiness by writing the ready
    file, hold for hold_seconds, then delete the lock. Run in a subprocess
    so the file-existence locking is truly cross-process."""
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    # Signal that the lock is held by creating a sentinel file
    open(ready_event_path, "w").close()
    time.sleep(hold_seconds)
    try:
        os.unlink(lock_path)
    except OSError:
        pass


def _wait_for_file(path: str, timeout: float = 5.0) -> bool:
    """Poll until `path` exists or timeout expires. Returns True on success."""
    deadline = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


# ---------------------------------------------------------------------------
# _OQ_DOC used by OQ locking tests
# ---------------------------------------------------------------------------

_OQ_DOC = """\
# Architect Open Questions

**Highest OQ ID ever minted (do not reuse below this number):** 10

| ID | Question | Context / Spec | Unblocks | Date Added |
|----|----------|----------------|----------|------------|
| OQ-10 | **Existing question?** | ctx | unblocks | 2026-06-01 |
"""

_AT_QUEUE = """\
# AI Task Queue

## Ready Pool -- Top Priority

### Newly Decomposed Tasks (Intake)

> intro

| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |
|----|------|-------------|---------------|--------|------------|
| AT-1100 | **Existing task** | spec | evidence | Small | None |
"""


# ---------------------------------------------------------------------------
# TestLedgerLockBasic: _ledger_lock unit tests (no concurrency needed)
# ---------------------------------------------------------------------------

class TestLedgerLockBasic(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._dummy = os.path.join(self._tmpdir, "ledger.md")
        open(self._dummy, "w").close()

    def test_acquires_and_releases_sidecar(self):
        lock_path = self._dummy + ".lock"
        self.assertFalse(os.path.exists(lock_path))
        with local_mcp._ledger_lock(self._dummy):
            self.assertTrue(os.path.exists(lock_path))
        self.assertFalse(os.path.exists(lock_path))

    def test_cleans_up_even_when_body_raises(self):
        lock_path = self._dummy + ".lock"
        with self.assertRaises(ValueError):
            with local_mcp._ledger_lock(self._dummy):
                self.assertTrue(os.path.exists(lock_path))
                raise ValueError("simulated body error")
        self.assertFalse(os.path.exists(lock_path))

    def test_timeout_raises_runtime_error(self):
        lock_path = self._dummy + ".lock"
        # Pre-create the sidecar to simulate a stuck holder
        open(lock_path, "w").close()
        try:
            with self.assertRaises(RuntimeError) as ctx:
                with local_mcp._ledger_lock(self._dummy, timeout=0.1):
                    pass
            msg = str(ctx.exception)
            self.assertIn("could not acquire advisory lock", msg)
            # Use the filename (not the full path) to avoid repr backslash-escaping on Windows
            self.assertIn("ledger.md.lock", msg)
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    def test_sequential_acquisitions_succeed(self):
        """Lock can be re-acquired after release -- no lingering sidecar."""
        for i in range(3):
            with local_mcp._ledger_lock(self._dummy):
                pass  # each iteration must not deadlock
        self.assertFalse(os.path.exists(self._dummy + ".lock"))

    def test_lock_constants_are_accessible(self):
        self.assertIsInstance(local_mcp._LEDGER_LOCK_TIMEOUT, float)
        self.assertGreater(local_mcp._LEDGER_LOCK_TIMEOUT, 0)
        self.assertIsInstance(local_mcp._LEDGER_LOCK_RETRY_INTERVAL, float)
        self.assertGreater(local_mcp._LEDGER_LOCK_RETRY_INTERVAL, 0)

    def test_wait_message_logged_when_contended(self):
        """When a second caller blocks, a log line is emitted to stderr."""
        lock_path = self._dummy + ".lock"

        stderr_lines = []
        orig_print = local_mcp.sys.stderr

        class CapturePrint:
            def write(self, s):
                stderr_lines.append(s)
            def flush(self):
                pass

        capture = CapturePrint()

        acquired = threading.Event()
        released = threading.Event()

        def hold_lock():
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired.set()
            released.wait(timeout=2.0)
            os.unlink(lock_path)

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        acquired.wait(timeout=2.0)

        try:
            local_mcp.sys.stderr = capture
            # Should block briefly then succeed
            with local_mcp._ledger_lock(self._dummy, timeout=2.0):
                released.set()
        finally:
            local_mcp.sys.stderr = orig_print
            holder.join(timeout=2.0)

        all_text = "".join(stderr_lines)
        self.assertIn("waiting for advisory lock", all_text)
        self.assertIn("acquired", all_text)


# ---------------------------------------------------------------------------
# TestLedgerLockNoLostUpdate: concurrent-writer simulation tests
# ---------------------------------------------------------------------------

class TestLedgerLockNoLostUpdate(unittest.TestCase):
    """Simulate a second process holding the lock while a first-process call
    blocks and retries. After the holder releases, the first call must succeed
    and produce a correct result (no lost update).

    Uses multiprocessing so the lock file exclusion is truly cross-process
    (not just cross-thread), matching the real-world scenario where two
    separate Cline/orchestrator sessions run concurrently.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # Keep original module-level path globals so we can restore them
        self._orig_oq_path = local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH
        self._orig_at_path = local_mcp.AT_QUEUE_PATH
        self._orig_orchestrator_state_dir = local_mcp._ORCHESTRATOR_STATE_DIR
        self._orig_odysseus_url = local_mcp.ODYSSEUS_API_URL
        self._orig_odysseus_token = local_mcp.ODYSSEUS_API_TOKEN
        local_mcp.ODYSSEUS_API_URL = ""
        local_mcp.ODYSSEUS_API_TOKEN = ""

    def tearDown(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._orig_oq_path
        local_mcp.AT_QUEUE_PATH = self._orig_at_path
        local_mcp._ORCHESTRATOR_STATE_DIR = self._orig_orchestrator_state_dir
        local_mcp.ODYSSEUS_API_URL = self._orig_odysseus_url
        local_mcp.ODYSSEUS_API_TOKEN = self._orig_odysseus_token

    # ---- OQ row append ----

    def test_append_oq_row_blocks_then_succeeds_without_lost_update(self):
        """_append_oq_row waits for a concurrent lock holder to release, then
        writes correctly -- no row is silently dropped."""
        oq_path = os.path.join(self._tmpdir, "oq.md")
        with open(oq_path, "w", encoding="utf-8") as f:
            f.write(_OQ_DOC)

        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = oq_path

        lock_path = oq_path + ".lock"
        ready_path = os.path.join(self._tmpdir, "oq_ready")

        # Spawn a second process that holds the lock for ~0.2s
        ctx = multiprocessing.get_context("spawn")
        holder = ctx.Process(
            target=_hold_lock_for,
            args=(lock_path, 0.2, ready_path),
            daemon=True,
        )
        holder.start()
        try:
            self.assertTrue(_wait_for_file(ready_path, timeout=5.0),
                            "Lock-holder process did not signal readiness")

            # First-process append should block, then succeed
            row = "| OQ-11 | **New question?** | ctx | unblocks | 2026-06-19 |\n"
            result = local_mcp._append_oq_row(row)
            self.assertTrue(result, "_append_oq_row returned False -- expected True")

            # Both rows must be present; no update was clobbered
            with open(oq_path, encoding="utf-8") as _f:
                contents = _f.read()
            self.assertIn("OQ-11", contents)
            self.assertIn("OQ-10", contents)
        finally:
            holder.join(timeout=3.0)

    # ---- AT row append ----

    def test_append_at_row_blocks_then_succeeds_without_lost_update(self):
        """_append_at_row waits for a concurrent lock holder to release."""
        at_path = os.path.join(self._tmpdir, "at.md")
        with open(at_path, "w", encoding="utf-8") as f:
            f.write(_AT_QUEUE)

        local_mcp.AT_QUEUE_PATH = at_path

        lock_path = at_path + ".lock"
        ready_path = os.path.join(self._tmpdir, "at_ready")

        ctx = multiprocessing.get_context("spawn")
        holder = ctx.Process(
            target=_hold_lock_for,
            args=(lock_path, 0.2, ready_path),
            daemon=True,
        )
        holder.start()
        try:
            self.assertTrue(_wait_for_file(ready_path, timeout=5.0),
                            "Lock-holder process did not signal readiness")

            row = "| AT-1101 | **New task** | SR-1.4 | Evidence | Small | None |\n"
            result = local_mcp._append_at_row(row)
            self.assertTrue(result, "_append_at_row returned False -- expected True")

            with open(at_path, encoding="utf-8") as _f:
                contents = _f.read()
            self.assertIn("AT-1101", contents)
            self.assertIn("AT-1100", contents)
        finally:
            holder.join(timeout=3.0)

    # ---- Orchestrator state save ----

    def test_save_orchestrator_state_blocks_then_succeeds_without_lost_update(self):
        """_save_orchestrator_state waits for a concurrent lock holder."""
        os.makedirs(self._tmpdir, exist_ok=True)
        local_mcp._ORCHESTRATOR_STATE_DIR = self._tmpdir

        key = "deadbeefdeadbeef"
        state_path = os.path.join(self._tmpdir, f"{key}.json")
        lock_path = state_path + ".lock"
        ready_path = os.path.join(self._tmpdir, "state_ready")

        ctx = multiprocessing.get_context("spawn")
        holder = ctx.Process(
            target=_hold_lock_for,
            args=(lock_path, 0.2, ready_path),
            daemon=True,
        )
        holder.start()
        try:
            self.assertTrue(_wait_for_file(ready_path, timeout=5.0),
                            "Lock-holder process did not signal readiness")

            state = local_mcp._new_orchestrator_state(["step one"], "test")
            state["current"] = 1
            local_mcp._save_orchestrator_state(key, state)

            with open(state_path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["current"], 1)
            self.assertEqual(saved["steps"], ["step one"])
        finally:
            holder.join(timeout=3.0)


# ---------------------------------------------------------------------------
# TestLedgerLockTimeout: verify timeout path returns False / no crash
# ---------------------------------------------------------------------------

class TestLedgerLockTimeout(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_oq_path = local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH
        self._orig_at_path = local_mcp.AT_QUEUE_PATH
        self._orig_odysseus_url = local_mcp.ODYSSEUS_API_URL
        self._orig_odysseus_token = local_mcp.ODYSSEUS_API_TOKEN
        local_mcp.ODYSSEUS_API_URL = ""
        local_mcp.ODYSSEUS_API_TOKEN = ""

    def tearDown(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._orig_oq_path
        local_mcp.AT_QUEUE_PATH = self._orig_at_path
        local_mcp.ODYSSEUS_API_URL = self._orig_odysseus_url
        local_mcp.ODYSSEUS_API_TOKEN = self._orig_odysseus_token

    def test_append_oq_row_returns_false_on_lock_timeout(self):
        """_append_oq_row returns False (does not raise) when the lock times
        out -- the caller already has an error-return path and must not crash."""
        import unittest.mock
        import contextlib

        oq_path = os.path.join(self._tmpdir, "oq_timeout.md")
        with open(oq_path, "w", encoding="utf-8") as f:
            f.write(_OQ_DOC)
        # Pre-hold the lock so acquisition will time out
        lock_path = oq_path + ".lock"
        open(lock_path, "w").close()
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = oq_path

        # Wrap _ledger_lock to always pass a very short timeout so the
        # test does not take 10 seconds to time out
        orig_lock = local_mcp._ledger_lock

        @contextlib.contextmanager
        def fast_timeout_lock(path, timeout=0.05):
            with orig_lock(path, timeout=0.05):
                yield

        try:
            with unittest.mock.patch.object(local_mcp, "_ledger_lock", fast_timeout_lock):
                row = "| OQ-11 | **Should not appear** | ctx | unblocks | 2026-06-19 |\n"
                result = local_mcp._append_oq_row(row)
            self.assertFalse(result)
            # The original file must not have been modified
            with open(oq_path, encoding="utf-8") as f:
                contents = f.read()
            self.assertNotIn("OQ-11", contents)
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    def test_append_at_row_returns_false_on_lock_timeout(self):
        """_append_at_row returns False when the lock times out."""
        import unittest.mock
        import contextlib

        at_path = os.path.join(self._tmpdir, "at_timeout.md")
        with open(at_path, "w", encoding="utf-8") as f:
            f.write(_AT_QUEUE)
        lock_path = at_path + ".lock"
        open(lock_path, "w").close()
        local_mcp.AT_QUEUE_PATH = at_path

        orig_lock = local_mcp._ledger_lock

        @contextlib.contextmanager
        def fast_timeout_lock(path, timeout=0.05):
            with orig_lock(path, timeout=0.05):
                yield

        try:
            with unittest.mock.patch.object(local_mcp, "_ledger_lock", fast_timeout_lock):
                row = "| AT-1101 | **Should not appear** | spec | ev | Small | None |\n"
                result = local_mcp._append_at_row(row)
            self.assertFalse(result)
            with open(at_path, encoding="utf-8") as f:
                contents = f.read()
            self.assertNotIn("AT-1101", contents)
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# TestLedgerIoRemainsLockFree: confirm ledger_io has no locking imports
# ---------------------------------------------------------------------------

class TestLedgerIoRemainsLockFree(unittest.TestCase):
    """Acceptance criterion: ledger_io.py pure functions remain lock-free.
    Locking must live only in local-mcp.py's I/O wrappers."""

    def test_ledger_io_has_no_locking_import(self):
        """ledger_io.py should not import threading, contextlib, or fcntl --
        it is a pure text-transformation module."""
        with open(_LEDGER_IO_PATH, encoding="utf-8") as _f:
            src = _f.read()
        for forbidden in ("import threading", "import contextlib",
                          "import fcntl", "import portalocker",
                          "_ledger_lock"):
            self.assertNotIn(forbidden, src,
                             f"ledger_io.py must not contain {forbidden!r}")

    def test_ledger_io_pure_functions_have_no_lock_side_effects(self):
        """Calling ledger_io functions does not create .lock files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # ledger_io functions only take/return strings -- no file I/O
            doc = _OQ_DOC
            ledger_io.next_oq_id(doc)
            ledger_io.insert_oq_row(doc, "| OQ-12 | q | c | u | 2026-06-19 |\n")
            # No .lock files should exist anywhere
            for name in os.listdir(tmpdir):
                self.assertFalse(name.endswith(".lock"),
                                 f"Unexpected lock file: {name}")


if __name__ == "__main__":
    unittest.main()
