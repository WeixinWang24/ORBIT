#!/usr/bin/env bash
# ORBIT local bootstrap — run once after cloning / moving the repo to a new machine.
#
# Usage:
#   ./scripts/bootstrap.sh                      # full setup (conda env + pip + .env.local + auth)
#   ./scripts/bootstrap.sh auth                 # seed OpenAI credentials (PKCE browser flow, default)
#   ./scripts/bootstrap.sh auth paste           # seed via copy-paste JSON blob
#   ./scripts/bootstrap.sh auth <file>          # seed from a JSON credential file
#   ./scripts/bootstrap.sh obsidian             # configure Obsidian vault path (interactive)
#   ./scripts/bootstrap.sh obsidian /path/to/v  # set vault path directly
#   ./scripts/bootstrap.sh obsidian clear       # clear vault path / disable Obsidian
#
# OpenAI auth — PKCE flow (default):
#   1. Script prints an authorization URL.
#   2. Open it in a browser and authorize ORBIT.
#   3. Copy the full redirect URL (or just the "code=..." value) from the browser bar.
#   4. Paste it back into the terminal prompt.
#   Tokens are exchanged automatically and saved to .runtime/openai_oauth_credentials.json.
#
# OpenAI auth — paste fallback:
#   ./scripts/bootstrap.sh auth paste
#   Paste a raw JSON credential blob:
#     { "access_token": "sess-...", "refresh_token": "...",
#       "expires_at_epoch_ms": 9999999999000, "account_email": "you@example.com" }

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV_NAME="Orbit"
ENV_FILE="$REPO_ROOT/config/environment.yml"
ENV_LOCAL="$REPO_ROOT/.env.local"
CRED_DIR="$REPO_ROOT/.runtime"
CRED_FILE="$CRED_DIR/openai_oauth_credentials.json"

# ── colour helpers ─────────────────────────────────────────────────────────────
bold=$'\033[1m'; green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; reset=$'\033[0m'
info()  { echo "${green}▶${reset} $*"; }
warn()  { echo "${yellow}⚠${reset}  $*"; }
err()   { echo "${red}✗${reset}  $*" >&2; }
step()  { echo ""; echo "${bold}── $* ──${reset}"; }

# ── resolve conda ──────────────────────────────────────────────────────────────
_find_conda() {
    if command -v conda &>/dev/null; then return 0; fi
    for p in "$HOME/anaconda3/bin/conda" "$HOME/miniconda3/bin/conda" \
              "/opt/conda/bin/conda" "/usr/local/anaconda3/bin/conda"; do
        [[ -x "$p" ]] && { export PATH="$(dirname "$p"):$PATH"; return 0; }
    done
    return 1
}

# ── .env.local in-place variable setter ───────────────────────────────────────
# Usage: _set_env_local_var VAR_NAME "value"
# Replaces "export VAR_NAME=..." if present, otherwise appends.
# Uses Python for safe handling of paths with special characters.
_set_env_local_var() {
    local var="$1" val="$2"
    VAR="$var" VAL="$val" ENV_LOCAL_PATH="$ENV_LOCAL" python3 - <<'PYEOF'
import os, re, pathlib

path = pathlib.Path(os.environ["ENV_LOCAL_PATH"])
var  = os.environ["VAR"]
val  = os.environ["VAL"]

if not path.exists():
    path.write_text(f"export {var}={val}\n", encoding="utf-8")
    exit(0)

text = path.read_text(encoding="utf-8")
pattern = rf'^export {re.escape(var)}=.*$'
replacement = f"export {var}={val}"
if re.search(pattern, text, flags=re.MULTILINE):
    new_text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
else:
    new_text = text.rstrip("\n") + f"\nexport {var}={val}\n"
path.write_text(new_text, encoding="utf-8")
PYEOF
}

# ── auth: PKCE browser flow ────────────────────────────────────────────────────
_auth_pkce() {
    echo ""
    info "Starting OpenAI OAuth PKCE flow…"
    # Write the script to a temp file so Python's input() reads from the real
    # terminal (stdin) rather than from the heredoc that would otherwise
    # supply it, which causes immediate EOFError.
    local tmpscript
    tmpscript="$(mktemp /tmp/orbit_pkce_XXXXXX.py)"
    cat > "$tmpscript" <<'PYEOF'
import os, sys, time
sys.path.insert(0, os.path.join(os.environ["ORBIT_REPO_ROOT"], "src"))
from pathlib import Path
from orbit.runtime.auth.oauth.openai_oauth_pkce import create_openai_oauth_pkce_session
from orbit.runtime.auth.oauth.openai_oauth_exchange import exchange_callback_input_and_persist, OpenAIOAuthExchangeError

repo_root = Path(os.environ["ORBIT_REPO_ROOT"])
session = create_openai_oauth_pkce_session()

print()
print("  Open this URL in your browser:")
print()
print(f"    {session.authorize_url}")
print()
print("  After authorizing, copy the full redirect URL from the browser address bar")
print("  (it starts with http://localhost:1455/auth/callback?code=...)")
print("  or paste just the code value.  Ctrl-C to abort.")
print()

try:
    callback_input = input("  Paste here → ").strip()
except (KeyboardInterrupt, EOFError):
    print("\nAborted.")
    sys.exit(1)

if not callback_input:
    print("Nothing pasted — aborted.")
    sys.exit(1)

try:
    result = exchange_callback_input_and_persist(
        repo_root=repo_root,
        pkce_session=session,
        callback_input=callback_input,
    )
except OpenAIOAuthExchangeError as exc:
    print(f"\n  Error: {exc}", file=sys.stderr)
    sys.exit(1)

ttl_h = (result.expires_at_epoch_ms - int(time.time() * 1000)) / 3_600_000
print()
print(f"  saved to: {result.credential_path}")
print(f"  account:  {result.account_email or '(not set)'}")
print(f"  expires:  {ttl_h:.1f} hours from now")
PYEOF
    ORBIT_REPO_ROOT="$REPO_ROOT" python3 "$tmpscript"
    rm -f "$tmpscript"
    info "OpenAI credentials saved."
}

# ── auth: copy-paste JSON blob ─────────────────────────────────────────────────
_auth_paste() {
    local json=""
    warn "Paste your OpenAI credential JSON below, then press Ctrl-D:"
    echo ""
    json="$(cat)"

    for field in access_token refresh_token expires_at_epoch_ms; do
        if ! echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); assert '$field' in d" 2>/dev/null; then
            err "JSON is missing required field: $field"; exit 1
        fi
    done

    mkdir -p "$CRED_DIR"
    CRED_FILE="$CRED_FILE" CRED_JSON="$json" python3 - <<'PYEOF'
import os, json, pathlib, time
data = json.loads(os.environ["CRED_JSON"])
out = {
    "access_token":        str(data["access_token"]),
    "refresh_token":       str(data["refresh_token"]),
    "expires_at_epoch_ms": int(data["expires_at_epoch_ms"]),
    "account_email":       str(data["account_email"]) if data.get("account_email") else None,
}
p = pathlib.Path(os.environ["CRED_FILE"])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
os.chmod(p, 0o600)
ttl_h = (out["expires_at_epoch_ms"] - int(time.time() * 1000)) / 3_600_000
print(f"  saved to: {p}")
print(f"  account:  {out['account_email'] or '(not set)'}")
print(f"  expires:  {ttl_h:.1f} hours from now")
PYEOF
    info "OpenAI credentials saved."
}

# ── auth: from file ────────────────────────────────────────────────────────────
_auth_from_file() {
    local src="$1"
    info "Reading credentials from: $src"
    local json
    json="$(cat "$src")"
    CRED_FILE="$CRED_FILE" CRED_JSON="$json" python3 - <<'PYEOF'
import os, json, pathlib, time, sys
data = json.loads(os.environ["CRED_JSON"])
required = ["access_token", "refresh_token", "expires_at_epoch_ms"]
missing = [f for f in required if f not in data]
if missing:
    print(f"Error: JSON missing fields: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
out = {
    "access_token":        str(data["access_token"]),
    "refresh_token":       str(data["refresh_token"]),
    "expires_at_epoch_ms": int(data["expires_at_epoch_ms"]),
    "account_email":       str(data["account_email"]) if data.get("account_email") else None,
}
p = pathlib.Path(os.environ["CRED_FILE"])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
os.chmod(p, 0o600)
ttl_h = (out["expires_at_epoch_ms"] - int(time.time() * 1000)) / 3_600_000
print(f"  saved to: {p}")
print(f"  account:  {out['account_email'] or '(not set)'}")
print(f"  expires:  {ttl_h:.1f} hours from now")
PYEOF
    info "OpenAI credentials saved."
}

# ── subcommand: obsidian vault config ─────────────────────────────────────────
# Usage:
#   ./scripts/bootstrap.sh obsidian                   # prompt for vault path
#   ./scripts/bootstrap.sh obsidian /path/to/vault    # set directly
#   ./scripts/bootstrap.sh obsidian clear             # disable / clear the path
cmd_obsidian() {
    local vault_path="${1:-}"

    if [[ "$vault_path" == "clear" ]]; then
        step "Clearing Obsidian vault configuration"
        if [[ ! -f "$ENV_LOCAL" ]]; then
            err ".env.local not found — nothing to clear."; return 1
        fi
        _set_env_local_var "ORBIT_OBSIDIAN_VAULT_ROOT" ""
        _set_env_local_var "ORBIT_ENABLE_KNOWLEDGE" "0"
        info "ORBIT_OBSIDIAN_VAULT_ROOT cleared; knowledge features disabled."
        return 0
    fi

    if [[ -z "$vault_path" ]]; then
        # Show current value if set
        local current
        current="$(grep -oP '(?<=^export ORBIT_OBSIDIAN_VAULT_ROOT=).*' "$ENV_LOCAL" 2>/dev/null || true)"
        echo ""
        if [[ -n "$current" ]]; then
            info "Current vault path: $current"
        else
            info "No Obsidian vault configured yet."
        fi
        echo ""
        echo "  Enter the absolute path to your Obsidian vault directory,"
        echo "  or press Enter to skip (leaves Obsidian integration disabled)."
        echo ""
        read -r -p "  Vault path: " vault_path
        vault_path="${vault_path%/}"   # strip trailing slash
    fi

    if [[ -z "$vault_path" ]]; then
        warn "No path entered — Obsidian integration unchanged."
        return 0
    fi

    # Expand ~ manually since the user might type ~/...
    vault_path="${vault_path/#\~/$HOME}"

    if [[ ! -d "$vault_path" ]]; then
        err "Path does not exist or is not a directory: $vault_path"
        return 1
    fi

    if [[ ! -f "$ENV_LOCAL" ]]; then
        err ".env.local not found. Run: ./scripts/bootstrap.sh setup first."; return 1
    fi

    _set_env_local_var "ORBIT_OBSIDIAN_VAULT_ROOT" "$vault_path"
    _set_env_local_var "ORBIT_ENABLE_KNOWLEDGE" "1"
    info "Vault path saved:  $vault_path"
    info "ORBIT_ENABLE_KNOWLEDGE → 1  (knowledge retrieval enabled)"
    echo ""
    echo "  ${bold}Re-source your config to apply:${reset}"
    echo "    source .env.local"
    echo ""
}

# ── subcommand: auth (dispatcher) ─────────────────────────────────────────────
cmd_auth() {
    local mode="${1:-pkce}"
    case "$mode" in
        pkce)   _auth_pkce ;;
        paste)  _auth_paste ;;
        *)
            if [[ -f "$mode" ]]; then
                _auth_from_file "$mode"
            else
                err "Unknown auth mode: '$mode'  (valid: pkce | paste | <file>)"
                exit 1
            fi
            ;;
    esac
}

# ── subcommand: full setup ─────────────────────────────────────────────────────
cmd_setup() {
    step "Conda environment"
    if ! _find_conda; then
        err "conda not found. Install Anaconda or Miniconda first."; exit 1
    fi
    local conda_base
    conda_base="$(conda info --base 2>/dev/null)"
    # shellcheck disable=SC1091
    source "$conda_base/etc/profile.d/conda.sh"

    if conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME"; then
        info "Conda env '$CONDA_ENV_NAME' exists — updating packages."
        conda env update -n "$CONDA_ENV_NAME" -f "$ENV_FILE" --prune
    else
        info "Creating conda env '$CONDA_ENV_NAME' from $ENV_FILE"
        conda env create -f "$ENV_FILE"
    fi

    step "Activating env and verifying editable install"
    conda activate "$CONDA_ENV_NAME"
    if ! python -c "import orbit" &>/dev/null; then
        info "Installing orbit in editable mode."
        pip install -e "$REPO_ROOT"
    else
        info "orbit package already importable."
    fi

    step "Local config (.env.local)"
    if [[ -f "$ENV_LOCAL" ]]; then
        info ".env.local already exists — skipping."
    else
        warn ".env.local missing — creating from template."
        cat > "$ENV_LOCAL" <<'EOF'
# ORBIT local machine configuration
# Source before running orbit:  source .env.local

export ORBIT_STORE_BACKEND=sqlite
export ORBIT_OBSIDIAN_VAULT_ROOT=
export ORBIT_ENABLE_KNOWLEDGE=0
EOF
        info ".env.local created."
    fi

    step "Obsidian vault (optional)"
    # Prompt only when vault is not yet set (empty or absent in .env.local).
    local current_vault
    current_vault="$(grep -oP '(?<=^export ORBIT_OBSIDIAN_VAULT_ROOT=)\S.*' "$ENV_LOCAL" 2>/dev/null || true)"
    if [[ -n "$current_vault" ]]; then
        info "Obsidian vault already configured: $current_vault"
    else
        cmd_obsidian || true
    fi

    step "OpenAI credentials"
    if [[ -f "$CRED_FILE" ]]; then
        info "Credential file already exists at $CRED_FILE"
    else
        warn "No credential file found."
        echo ""
        echo "  How would you like to authenticate?"
        echo "    ${bold}pkce${reset}   — browser OAuth flow  (recommended)"
        echo "    ${bold}paste${reset}  — paste a JSON credential blob"
        echo "    ${bold}skip${reset}   — do it later  (./scripts/bootstrap.sh auth)"
        echo ""
        read -r -p "  Choice [pkce/paste/skip]: " ans
        case "${ans,,}" in
            pkce)   _auth_pkce ;;
            paste)  _auth_paste ;;
            skip|"") warn "Skipping. Run later:  ./scripts/bootstrap.sh auth [pkce|paste|<file>]" ;;
            *)      warn "Unrecognised choice — skipping auth." ;;
        esac
    fi

    step "Done"
    echo ""
    echo "  ${bold}To start ORBIT:${reset}"
    echo "    conda activate $CONDA_ENV_NAME"
    echo "    source .env.local"
    echo "    orbit"
    echo ""
}

# ── dispatch ───────────────────────────────────────────────────────────────────
case "${1:-setup}" in
    auth)     cmd_auth "${2:-pkce}" ;;
    setup)    cmd_setup ;;
    obsidian) cmd_obsidian "${2:-}" ;;
    *)        err "Unknown subcommand: '$1'  (valid: setup | auth [pkce|paste|<file>] | obsidian [path|clear])"; exit 1 ;;
esac
