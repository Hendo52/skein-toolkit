#!/usr/bin/env bash
# =============================================================================
# provision-devserver.sh
# Full dev environment setup for a fresh Vast.ai/RunPod Ubuntu GPU instance.
#
# Run this once after renting a new instance:
#   ssh -p <port> root@<ip> "bash -s" < scripts/provision-devserver.sh
#
# Or copy it to the instance and run it there:
#   scp -P <port> scripts/provision-devserver.sh root@<ip>:/tmp/
#   ssh -p <port> root@<ip> "bash /tmp/provision-devserver.sh"
#
# After this script completes:
#   - The repo is at ~/repo
#   - yarn build works
#   - Python .venv is set up
#   - Ollama is running (model loaded if persistent volume is attached)
#   - Xvfb is running on :99 for Playwright
#   - git is configured for commits (you will be prompted for GitHub credentials)
# =============================================================================

set -euo pipefail

REPO_URL="https://github.com/Hendo52/Electron-Splines.git"
REPO_DIR="$HOME/repo"
NODE_VERSION="20"

echo "============================================================"
echo " Electron-Splines Dev Server Provisioning"
echo " $(date)"
echo "============================================================"

# --- 1. System packages ---
echo ""
echo "[1/9] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    git curl wget xvfb \
    python3 python3-pip python3-venv \
    build-essential libssl-dev \
    ca-certificates gnupg lsb-release \
    software-properties-common

# --- 2. Node.js 20.x ---
echo ""
echo "[2/9] Installing Node.js $NODE_VERSION..."
if ! command -v node &>/dev/null || [[ "$(node --version | cut -d. -f1 | tr -d 'v')" -lt "$NODE_VERSION" ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_VERSION}.x" | bash -
    apt-get install -y nodejs
fi
npm install -g yarn --quiet
echo "  node $(node --version), yarn $(yarn --version)"

# --- 3. OpenSCAD CLI ---
echo ""
echo "[3/9] Installing OpenSCAD..."
if ! command -v openscad &>/dev/null; then
    add-apt-repository -y ppa:openscad/releases 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq openscad
fi
# The project uses openscad.com as the command name
if [ ! -f /usr/local/bin/openscad.com ]; then
    ln -sf "$(command -v openscad)" /usr/local/bin/openscad.com
fi
echo "  openscad $(openscad --version 2>&1 | head -1)"

# --- 4. Ollama ---
echo ""
echo "[4/9] Installing Ollama and registering as a persistent systemd service..."
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
# Register Ollama as a systemd service bound to all interfaces.
# OLLAMA_HOST=0.0.0.0:11434 is required so that the SSH LocalForward tunnel
# (written by launch-devserver.ps1) correctly reaches this service.
# Without 0.0.0.0 binding, the forwarded connection is refused.
OLLAMA_SVC=/etc/systemd/system/ollama.service
if systemctl is-active --quiet ollama 2>/dev/null; then
    echo "  Ollama systemd service already running -- skipping install."
else
    cat > "$OLLAMA_SVC" << 'SVCEOF'
[Unit]
Description=Ollama LLM Server
After=network-online.target

[Service]
Type=simple
User=root
Environment=OLLAMA_HOST=0.0.0.0:11434
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
    systemctl daemon-reload
    systemctl enable ollama
    systemctl start ollama
    sleep 5
    echo "  Ollama systemd service installed and started."
fi
echo "  Ollama status: $(systemctl is-active ollama)"
echo "  Checking for models..."
ollama list || echo "  (No models yet)"
echo ""
echo "  MODELS FOR INTERACTIVE SESSIONS (pull once per persistent volume):"
echo "    ollama pull qwen2.5-coder:7b     # Inference: Local-Fast completions (~4 GB VRAM)"
echo "    ollama pull llama3.3:70b         # Inference: Local-Agent chat     (~40 GB VRAM)"
echo "    ollama pull deepseek-r1:32b      # Inference: Local-Agent reasoning (~20 GB VRAM)"
echo "  Each pull takes 5-40 min. Attach ollama-models volume at /root/.ollama to persist."

# --- 5. Clone repo ---
echo ""
echo "[5/9] Cloning repo..."
if [ -d "$REPO_DIR/.git" ]; then
    echo "  Repo already exists at $REPO_DIR -- pulling latest..."
    cd "$REPO_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi
git submodule update --init --recursive
echo "  Repo ready at $REPO_DIR ($(git log --oneline -1))"

# --- 6. Node dependencies ---
echo ""
echo "[6/9] Running yarn install..."
cd "$REPO_DIR"
yarn install --frozen-lockfile --silent
echo "  node_modules ready"

# --- 7. Python virtualenv ---
echo ""
echo "[7/9] Setting up Python virtualenv..."
cd "$REPO_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -q trimesh numpy scipy shapely networkx rtree
echo "  .venv ready"

# --- 8. Xvfb (virtual display for Playwright) ---
echo ""
echo "[8/9] Starting Xvfb on :99..."
if ! pgrep -x Xvfb &>/dev/null; then
    Xvfb :99 -screen 0 1280x800x24 &
    sleep 2
fi
export DISPLAY=:99
echo "  Xvfb running on :99"

# --- 9. Git identity for commits ---
echo ""
echo "[9/9] Configuring git identity..."
if [ -z "$(git config --global user.name 2>/dev/null)" ]; then
    echo "  Enter your git user.name (used for commits from this server):"
    read -r GIT_NAME
    git config --global user.name "$GIT_NAME"
fi
if [ -z "$(git config --global user.email 2>/dev/null)" ]; then
    echo "  Enter your git user.email:"
    read -r GIT_EMAIL
    git config --global user.email "$GIT_EMAIL"
fi

# Store HTTPS credentials so agents can git push without interactive prompts.
# You will be prompted for your GitHub username + Personal Access Token (PAT)
# the first time you push. The PAT needs 'repo' scope.
git config --global credential.helper store

echo ""
echo "  Git identity: $(git config --global user.name) <$(git config --global user.email)>"
echo "  Credential helper: store (~/.git-credentials will be written on first push)"

# --- Done ---
echo ""
echo "============================================================"
echo " Provisioning complete!"
echo "============================================================"
echo ""
echo " Repo:    $REPO_DIR"
echo " Node:    $(node --version)"
echo " Yarn:    $(yarn --version)"
echo " Python:  $(python3 --version)"
echo " Ollama:  $(ollama list 2>/dev/null | head -5 || echo 'running (no models yet)')"
echo " Display: DISPLAY=:99 (Xvfb)"
echo ""
echo " Next steps:"
echo "  1. Connect via VS Code Remote-SSH (run scripts\\launch-devserver.ps1 on your Windows PC)"
echo "  2. If Ollama has no models, run: ollama pull llama3.3:70b"
echo "  3. Verify the build: cd $REPO_DIR && yarn build"
echo "  4. On first git push you will be prompted for your GitHub PAT"
echo ""
echo " IMPORTANT: Add DISPLAY=:99 to /etc/environment so Playwright works in new shells:"
echo "  echo 'DISPLAY=:99' >> /etc/environment"
