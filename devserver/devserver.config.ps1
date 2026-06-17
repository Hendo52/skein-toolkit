# =============================================================================
# Development Server Configuration  --  REPO DEFAULTS
# =============================================================================
# This file contains repo-level defaults. Do NOT put personal settings here.
#
# Personal settings (API key, SSH key path, repo URL) live in:
#   ~/.devserver-config.ps1
#
# Run scripts\setup-devserver.ps1 to generate your personal config.
# =============================================================================

# ---------------------------------------------------------------------------
# Repo-level defaults (overridden by ~/.devserver-config.ps1 if present)
# ---------------------------------------------------------------------------

# Path to your SSH private key for Vast.ai
$DevServerKey = "$env:USERPROFILE\.ssh\vast_key"

# Repo path on the remote instance
$DevServerRepo = "/root/repo"

# Git repo URL cloned onto a fresh instance (empty = skip clone step)
$DevServerRepoUrl = ''

# GitHub personal access token for cloning private repos.
# Required if DevServerRepoUrl points to a private repository.
# Scopes needed: Contents (read-only) under Fine-grained tokens, or 'repo' for classic.
# Generate at: https://github.com/settings/tokens
# The setup wizard stores this securely under LOCALAPPDATA and keeps this
# config entry blank for compatibility only.
# Leave blank for public repos.
# IMPORTANT: Do not commit any token value here.
$DevServerGitHubToken = ''

# ---------------------------------------------------------------------------
# Use case definitions
# ---------------------------------------------------------------------------
# Each entry defines a named use case with:
#   models      -- ordered list of Ollama model tags to pull and expose in Continue.dev
#   min_vram_gb -- minimum GPU VRAM required (filters offers)
#   max_cost_hr -- price ceiling in USD/hr (filters offers)
#   label       -- display name shown in the selection menu
#
# To add a custom use case or override an existing one, add entries to
# ~/.devserver-config.ps1 AFTER the $DevServerUseCases line, e.g.:
#
#   $DevServerUseCases['mycase'] = @{
#       models      = @('mistral:7b', 'codestral:22b')
#       min_vram_gb = 24
#       max_cost_hr = 0.50
#       label       = 'My custom case (mistral + codestral)'
#   }
#
# You can also override a default case:
#   $DevServerUseCases['chat'] = @{
#       models      = @('llama3.3:70b', 'qwen2.5-coder:14b', 'nomic-embed-text')
#       min_vram_gb = 48
#       max_cost_hr = 1.20
#       label       = 'Chat + 14b coder + embeddings'
#   }
# ---------------------------------------------------------------------------
$DevServerUseCases = [ordered]@{
    # daily: 32B baseline -- targets 24GB VRAM (RTX 3090/4090/A5000 reserved ~$0.20-0.40/hr)
    # qwen2.5-coder:32b Q4_K_M ~20GB; fits with headroom for KV cache.
    daily       = @{ models = @('qwen2.5-coder:32b', 'qwen2.5-coder:7b'); min_vram_gb = 24; max_cost_hr = 0.45; label = 'Daily baseline (qwen2.5-coder:32b + qwen2.5-coder:7b)' }
    # heavy: 70B on-demand -- use for the most challenging reasoning tasks only
    heavy       = @{ models = @('llama3.3:70b', 'qwen2.5-coder:7b');      min_vram_gb = 48; max_cost_hr = 1.20; label = 'Heavy (llama3.3:70b + qwen2.5-coder:7b, on-demand)' }
    batch       = @{ models = @('deepseek-r1:32b');                        min_vram_gb = 20; max_cost_hr = 0.60; label = 'Overnight batch (deepseek-r1:32b)' }
    completions = @{ models = @('qwen2.5-coder:7b');                       min_vram_gb = 12; max_cost_hr = 0.30; label = 'Completions only (qwen2.5-coder:7b)' }
}

# ---------------------------------------------------------------------------
# Per-model inference parameters (passed to Ollama via requestOptions)
# ---------------------------------------------------------------------------
# Context window (tokens). Ollama defaults to 2048 -- far too small for agentic
# coding (Claude Code's system prompt alone is ~8K tokens).
# Values fit within the min_vram_gb headroom for each model class.
$DevServerModelNumCtx = @{
    'qwen2.5-coder:7b'   = 32768  # 4.7GB model; 32K KV cache fits easily on any target GPU
    'qwen2.5-coder:14b'  = 16384
    'qwen2.5-coder:32b'  = 16384  # ~20GB on 24GB card; 16K leaves ~2GB for KV cache
    'llama3.3:70b'       = 16384  # ~42GB on 48GB card; 16K leaves ~4GB for KV cache
    'deepseek-r1:32b'    = 16384
}
$DevServerDefaultNumCtx = 8192   # safe floor for any unlisted model

# Per-model request timeouts (seconds). Larger/reasoning models need more time.
$DevServerModelTimeout = @{
    'qwen2.5-coder:7b'   = 120
    'qwen2.5-coder:14b'  = 180
    'qwen2.5-coder:32b'  = 300
    'llama3.3:70b'       = 300
    'deepseek-r1:32b'    = 600   # reasoning model -- chain-of-thought adds latency
}
$DevServerDefaultTimeout = 120

# ---------------------------------------------------------------------------
# Git identity (optional -- set in ~/.devserver-config.ps1 only, never here)
# ---------------------------------------------------------------------------
# When set, rent-devserver.ps1 writes git user.name / user.email to
# ~/.gitconfig on each provisioned instance so commits are attributed correctly.
# Each user adds their own values in their personal ~/.devserver-config.ps1;
# this file keeps the defaults blank so no identity leaks into the repo.
#
# To enable: add to ~/.devserver-config.ps1:
#   $DevServerGitUserName  = 'Your Name'
#   $DevServerGitUserEmail = 'you@example.com'
# ---------------------------------------------------------------------------
$DevServerGitUserName  = ''
$DevServerGitUserEmail = ''

# ---------------------------------------------------------------------------
# Claude BYOK (optional -- keep key in ~/.devserver-config.ps1 only, never here)
# ---------------------------------------------------------------------------
# When $DevServerAnthropicKey is set, these models are prepended to every
# generated Continue.dev config so Claude is available regardless of whether
# the GPU server is running. The key is read only from your personal config.
#
# To enable: add to ~/.devserver-config.ps1:
#   $DevServerAnthropicKey = 'sk-ant-...'
#   $DevServerClaudeModels = @(
#       @{ name = 'claude-sonnet-4-5'; label = 'Claude Sonnet (BYOK)'; timeout = 300 }
#       @{ name = 'claude-haiku-3-5';  label = 'Claude Haiku (BYOK)';  timeout = 120 }
#   )
# ---------------------------------------------------------------------------
$DevServerAnthropicKey = ''
$DevServerClaudeModels = @()

# ---------------------------------------------------------------------------
# Cloudflare Workers AI BYOK (optional -- keep key in ~/.devserver-config.ps1 only)
# ---------------------------------------------------------------------------
# Cloudflare Workers AI is ~10x cheaper than Vast.ai for interactive sessions:
# ~$0.04/hr at 200K tokens vs ~$0.40/hr on GPU. No instance to manage; no idle
# charges. Trade-off: 32K context cap, shared infra (latency can vary).
#
# Models available that match the project use cases:
#   @cf/qwen/qwen2.5-coder-32b-instruct  -- primary coder model
#   @cf/meta/llama-3.3-70b-instruct-fp8  -- heavy reasoning
#   @cf/deepseek-ai/deepseek-r1-distill-qwen-32b -- batch reasoning
#   @cf/baai/bge-base-en-v1.5            -- embeddings
#
# API endpoint: https://api.cloudflare.com/client/v4/accounts/<accountId>/ai/v1
# Provider in Continue.dev: openai (Workers AI is OpenAI-compatible)
# Token: Cloudflare API token with Workers AI:Read permission
#
# Free tier: 10,000 Neurons/day (~50 long requests). Paid: $5/month + per-token.
#
# To enable: add to ~/.devserver-config.ps1:
#   $DevServerCFAccountId = '<your 32-char account ID>'
#   $DevServerCFApiToken  = '<Workers AI API token>'
#   $DevServerCFModels    = @(
#       # Prefer models that report native function_calling in CF's model catalog
#       # (gpt-oss, llama-4-scout, qwen3-30b-a3b, mistral-small-3.1, llama-3.3) --
#       # they emit standard OpenAI tool_calls directly, unlike qwen2.5-coder-32b
#       # which emits non-standard <tools> XML the local-mcp.py proxy must rewrite.
#       # gpt-oss is a reasoning model -- set maxTokens generously (it spends
#       # completion tokens on chain-of-thought before the final answer; too
#       # small a budget yields an empty response with finish_reason: length).
#       @{ name = '@cf/openai/gpt-oss-20b';              label = 'CF gpt-oss:20b';       numCtx = 128000; maxTokens = 4096 }
#       @{ name = '@cf/openai/gpt-oss-120b';             label = 'CF gpt-oss:120b';      numCtx = 128000; maxTokens = 4096 }
#       @{ name = '@cf/qwen/qwen2.5-coder-32b-instruct'; label = 'CF qwen2.5-coder:32b'; numCtx = 32768 }
#       @{ name = '@cf/meta/llama-3.3-70b-instruct-fp8'; label = 'CF llama3.3:70b';      numCtx = 32768 }
#   )
# ---------------------------------------------------------------------------
$DevServerCFAccountId = ''
$DevServerCFApiToken  = ''
$DevServerCFModels    = @()

# ---------------------------------------------------------------------------
# Safety watcher defaults
# ---------------------------------------------------------------------------

# Stop the instance after this many minutes of Ollama idle (no model loaded).
$WatchIdleMinutes = 30

# Hard session cap in hours. Instance stops regardless of activity.
$WatchMaxSessionHours = 8

# Hard spend cap in USD for this session.
$WatchMaxSpendUsd = 8.00

# Path to the active tik/tok batch file. Set to '' to disable batch-aware mode.
# Point SKEIN_BATCH_FILE env-var to your project's tik/tok file (e.g. in your shell profile).
$BatchFilePath = if ($env:SKEIN_BATCH_FILE) { $env:SKEIN_BATCH_FILE } else { '' }

# ---------------------------------------------------------------------------
# Model cache (optional -- set in ~/.devserver-config.ps1 only, never here)
# ---------------------------------------------------------------------------
# When set, rent-devserver.ps1 restores Ollama model blobs from a cloud storage
# remote (via rclone) before pulling from Ollama registry. This turns a 40-min
# model download into a ~3-5 min restore on any machine -- solving the problem
# of Vast.ai volumes being host-locked (volume can't follow you to a new machine).
#
# Format: "<rclone-remote-name>:<bucket>/<prefix>"
# Example: "r2:my-bucket/ollama-models"
#
# Setup:
#   1. Create a Cloudflare R2 bucket (free tier: 10 GB; then $0.015/GB/month)
#   2. Install rclone locally: winget install Rclone.Rclone
#   3. Run: rclone config  -> choose s3, Cloudflare R2, enter Access Key ID + Secret
#   4. Test: rclone ls <remote-name>:<bucket>/
#   5. Populate cache once: ssh vast-devserver and manually run:
#        rclone sync /root/.ollama/models/ r2:my-bucket/ollama-models --progress --max-transfer 30G
#   6. Set the values below in ~/.devserver-config.ps1
#
# After the cache is populated, every new instance restores models from R2
# automatically. rent-devserver.ps1 also syncs newly pulled models back to the
# cache at the end of provisioning (in the background) so the cache stays current.
#
# To enable: add to ~/.devserver-config.ps1:
#   $DevServerModelCacheRclone        = 'r2:my-bucket/ollama-models'
#   $DevServerModelCacheMaxTransferGB = 30   # optional; default 30
# ---------------------------------------------------------------------------
$DevServerModelCacheRclone = ''

# Hard cap on data transferred per rclone run (restore + sync-back).
# rclone exits with error code 8 if this limit would be exceeded, preventing
# runaway Cloudflare R2 charges. Raise only if you are intentionally adding
# models that exceed the total.
# R2 free tier: 10 GB storage, 1M Class A ops/month, 10M Class B ops/month.
# Typical model set (32b + 7b + embed): ~25 GB stored; ~25 GB per new instance.
$DevServerModelCacheMaxTransferGB = 30

# ---------------------------------------------------------------------------
# MCP server tunnel port
# ---------------------------------------------------------------------------
# The agentic MCP server (devserver-mcp.py) runs on the remote at port 3100.
# The SSH tunnel maps this to a local port for client connections.
# 3101 (not 3100) avoids conflicting with the Skein MCP server (local-mcp.py) on 3100.
$DevServerMcpTunnelPort = 3101

# ---------------------------------------------------------------------------
# Load user personal config override (generated by setup-devserver.ps1)
# Overrides any of the above values with the user's local settings.
# ---------------------------------------------------------------------------
$_userConfig = Join-Path $env:USERPROFILE '.devserver-config.ps1'
if (Test-Path $_userConfig) { . $_userConfig }
