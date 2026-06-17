#!/usr/bin/env python3
"""
Unit tests for _scrub_secrets / _scrub_secrets_from_body.
AT-1170 (vibe-coding anti-pattern #7 "secrets in prompts") -- outbound
secret-scrubbing in _cf_proxy before forwarding to external CF models.

Run with:
  cd skein-toolkit
  .venv/Scripts/python.exe mcp-server/tests/test_local_mcp_secret_scrubber.py
"""

import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))
_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

_scrub = local_mcp._scrub_secrets
_scrub_body = local_mcp._scrub_secrets_from_body


class TestScrubSecrets(unittest.TestCase):
    def test_redacts_openai_style_key(self):
        text = "here is the key: sk-abcdefghijklmnopqrstuvwxyz123456"
        result = _scrub(text)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", result)
        self.assertIn("<REDACTED:openai-style-key>", result)

    def test_redacts_aws_access_key_id(self):
        text = "access key: AKIAIOSFODNN7EXAMPLE in the config"
        result = _scrub(text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", result)
        self.assertIn("<REDACTED:aws-access-key-id>", result)

    def test_redacts_env_style_assignment(self):
        text = "CF_API_KEY=abc123def456 was in the .env file"
        result = _scrub(text)
        self.assertNotIn("abc123def456", result)
        self.assertIn("<REDACTED:env-style-assignment>", result)

    def test_redacts_generic_secret_env_var(self):
        text = "LITELLM_MASTER_TOKEN=sk-1234567890 set in shell"
        result = _scrub(text)
        self.assertNotIn("sk-1234567890", result)
        self.assertIn("<REDACTED:", result)

    def test_leaves_non_secret_shaped_text_untouched(self):
        text = "Please review the PlatformApi credential storage spec in AT-1177."
        self.assertEqual(_scrub(text), text)

    def test_leaves_normal_code_identifiers_untouched(self):
        text = "function storeCredential(key: string): Promise<void> { ... }"
        self.assertEqual(_scrub(text), text)

    def test_empty_and_none_pass_through(self):
        self.assertEqual(_scrub(""), "")
        self.assertEqual(_scrub(None), None)

    def test_multiple_matches_in_one_string_all_redacted(self):
        text = "key1: sk-aaaaaaaaaaaaaaaaaaaa key2: sk-bbbbbbbbbbbbbbbbbbbb"
        result = _scrub(text)
        self.assertNotIn("sk-aaaaaaaaaaaaaaaaaaaa", result)
        self.assertNotIn("sk-bbbbbbbbbbbbbbbbbbbb", result)
        self.assertEqual(result.count("<REDACTED:openai-style-key>"), 2)


class TestScrubSecretsFromBody(unittest.TestCase):
    def test_scrubs_plain_string_content(self):
        body = {"model": "cf/kimi-k2.6", "messages": [
            {"role": "user", "content": "my key is sk-abcdefghijklmnopqrstuvwx"},
        ]}
        result = _scrub_body(body)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwx", result["messages"][0]["content"])

    def test_scrubs_typed_block_array_content(self):
        body = {"model": "cf/kimi-k2.6", "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "CF_API_KEY=supersecretvalue123 in env"},
            ]},
        ]}
        result = _scrub_body(body)
        self.assertNotIn("supersecretvalue123", result["messages"][0]["content"][0]["text"])

    def test_clean_body_unchanged_in_content(self):
        body = {"model": "cf/kimi-k2.6", "messages": [
            {"role": "user", "content": "What does AT-1177 implement?"},
        ]}
        result = _scrub_body(body)
        self.assertEqual(result["messages"][0]["content"], "What does AT-1177 implement?")

    def test_non_dict_messages_passed_through_unchanged(self):
        body = {"model": "cf/kimi-k2.6", "messages": "not-a-list-shaped-body"}
        result = _scrub_body(body)
        self.assertEqual(result, body)

    def test_preserves_other_message_fields(self):
        body = {"model": "cf/kimi-k2.6", "messages": [
            {"role": "assistant", "content": "clean text", "tool_calls": [{"id": "x"}]},
        ]}
        result = _scrub_body(body)
        self.assertEqual(result["messages"][0]["tool_calls"], [{"id": "x"}])


if __name__ == "__main__":
    unittest.main()
