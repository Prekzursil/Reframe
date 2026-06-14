#!/usr/bin/env bash
# wsl-verthor-bootstrap.sh — provision the verthor reframe env inside WSL2.
#
# Invoked FROM A FILE by wsl-verthor-bootstrap.ps1 as:
#     wsl bash /mnt/<drive>/.../wsl-verthor-bootstrap.sh <repo_url> <install_dir> [weights_url]
#
# CONTRACTS.md §4 gotcha (NON-NEGOTIABLE): this script is passed as bash's
# positional FILE argument — NEVER piped via stdin (`tr | bash`); mediapipe
# inside verthor consumes stdin and corrupts a piped script. Keep it that way.
#
# Best-effort by design (PLAN-P2 T5): every step logs loudly; a failure leaves
# a clear message and a non-zero exit — the app then relies on the T4b
# claude-shorts reframe fallback instead.

set -uo pipefail

REPO_URL="${1:-}"
INSTALL_DIR="${2:-$HOME/verthor}"
WEIGHTS_URL="${3:-}"

log() { echo "[verthor-bootstrap] $*" >&2; }
fail() { echo "FAILED:verthor-bootstrap $*"; exit 1; }

[ -n "$REPO_URL" ] || fail "usage: wsl-verthor-bootstrap.sh <repo_url> [install_dir] [weights_url]"

command -v git >/dev/null 2>&1 || fail "git is not installed in this distro (sudo apt install git)"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed in this distro (sudo apt install python3 python3-venv)"

# -- clone (or update) ---------------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
    log "existing checkout at $INSTALL_DIR — leaving sources as-is"
elif [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    fail "$INSTALL_DIR exists and is not a git checkout; move it aside first"
else
    log "cloning $REPO_URL -> $INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" || fail "git clone failed"
fi

cd "$INSTALL_DIR" || fail "cannot cd into $INSTALL_DIR"

# -- venv ------------------------------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    log "creating venv"
    python3 -m venv .venv || fail "python3 -m venv failed (install python3-venv)"
fi

log "installing requirements into the venv"
if [ -f "requirements.txt" ]; then
    ./.venv/bin/pip install --upgrade pip >/dev/null 2>&1
    ./.venv/bin/pip install -r requirements.txt || fail "pip install -r requirements.txt failed"
elif [ -f "pyproject.toml" ]; then
    ./.venv/bin/pip install --upgrade pip >/dev/null 2>&1
    ./.venv/bin/pip install . || fail "pip install . failed"
else
    log "WARNING: no requirements.txt/pyproject.toml found — skipping dep install"
fi

# -- weights (optional) -----------------------------------------------------------
if [ -n "$WEIGHTS_URL" ]; then
    mkdir -p weights
    base="weights/$(basename "${WEIGHTS_URL%%\?*}")"
    if [ -s "$base" ]; then
        log "weights already present: $base"
    else
        log "downloading weights: $WEIGHTS_URL"
        if command -v curl >/dev/null 2>&1; then
            curl -L --fail -o "$base" "$WEIGHTS_URL" || fail "weights download failed"
        else
            wget -O "$base" "$WEIGHTS_URL" || fail "weights download failed"
        fi
    fi
else
    log "no weights URL given — verthor's own setup/docs handle weights"
fi

log "venv: $INSTALL_DIR/.venv"
echo "SUCCESS:verthor-bootstrap $INSTALL_DIR ready"
