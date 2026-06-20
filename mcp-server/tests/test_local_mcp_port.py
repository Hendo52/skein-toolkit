#!/usr/bin/env python3
"""
Unit tests for local-mcp.py's MCP_PORT env var (2026-06-20).

Real incident this fixes: tray.py (odysseus) spawns one local-mcp.py
instance per workspace so Odysseus's chat has repo access across all 3
sibling repos, not just one. The port was hardcoded to 3100 in two places
(FastMCP's own constructor and the final uvicorn.run call) -- every
instance beyond the first would have failed immediately with "address
already in use." This caught the bug before it could reproduce live by
checking MCP_PORT actually reaches FastMCP's port setting, not just that
the env var is read into a module-level variable.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_port.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import os
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))


def _fresh_import_local_mcp():
    """A fresh re-exec of local-mcp.py -- MCP_PORT is read at module-exec
    time, so testing different env var values needs a fresh import each
    time, not the shared module-level import other test files use."""
    spec = importlib.util.spec_from_file_location("local_mcp_port_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMcpPortOverride(unittest.TestCase):
    def test_default_port_is_3100_when_env_var_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MCP_PORT", None)
            module = _fresh_import_local_mcp()
        self.assertEqual(module.MCP_PORT, 3100)
        self.assertEqual(module.mcp.settings.port, 3100)

    def test_env_var_override_reaches_fastmcp_settings(self):
        # The actual bug this guards against: MCP_PORT being read into a
        # module-level variable is not the same as it actually reaching
        # FastMCP's own port setting -- assert on mcp.settings.port itself.
        with patch.dict(os.environ, {"MCP_PORT": "3101"}):
            module = _fresh_import_local_mcp()
        self.assertEqual(module.MCP_PORT, 3101)
        self.assertEqual(module.mcp.settings.port, 3101)

    def test_two_instances_with_different_ports_do_not_collide(self):
        # Directly reproduces the real incident: two workspace MCP
        # instances, each with their own MCP_PORT, must end up with
        # different FastMCP port settings -- not both silently defaulting
        # to 3100.
        with patch.dict(os.environ, {"MCP_PORT": "3100"}):
            first = _fresh_import_local_mcp()
        with patch.dict(os.environ, {"MCP_PORT": "3101"}):
            second = _fresh_import_local_mcp()
        self.assertNotEqual(first.mcp.settings.port, second.mcp.settings.port)


if __name__ == "__main__":
    unittest.main()
