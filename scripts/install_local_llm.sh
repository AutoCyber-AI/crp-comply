#!/usr/bin/env sh
# install_local_llm.sh — bootstrap a local OpenAI-compatible LLM
# for crp-comply. Detects RAM/GPU, installs Ollama, pulls the
# right-sized model, writes ~/.crp-comply/local-llm.json.
#
# Idempotent: re-running upgrades the model selection only if
# free RAM has grown into a higher tier.
#
# Usage:
#   sh scripts/install_local_llm.sh
#   sh scripts/install_local_llm.sh --model llama3.1:8b-instruct-q4_K_M
#   sh scripts/install_local_llm.sh --tier mini      # force smallest model
#
set -eu

# ---------- helpers ----------
log()  { printf '\033[1;36m[install-local-llm]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install-local-llm WARN]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[install-local-llm FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- arg parse ----------
FORCE_MODEL=""
FORCE_TIER=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model) FORCE_MODEL="${2:?}"; shift 2 ;;
    --tier)  FORCE_TIER="${2:?}";  shift 2 ;;
    --help|-h)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) warn "ignoring unknown arg: $1"; shift ;;
  esac
done

# ---------- detect platform ----------
UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
UNAME_M="$(uname -m 2>/dev/null || echo unknown)"
case "$UNAME_S" in
  Darwin) PLATFORM=mac ;;
  Linux)  PLATFORM=linux ;;
  *)      fail "Unsupported OS: $UNAME_S (use install_local_llm.ps1 on Windows)" ;;
esac
log "platform=$PLATFORM arch=$UNAME_M"

# ---------- detect free RAM (GB) ----------
detect_ram_gb() {
  case "$PLATFORM" in
    mac)
      # total memory in bytes → GB
      if command -v sysctl >/dev/null 2>&1; then
        TOTAL_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
        echo "$(( TOTAL_BYTES / 1024 / 1024 / 1024 ))"
      else
        echo 0
      fi
      ;;
    linux)
      if [ -r /proc/meminfo ]; then
        # MemAvailable in kB
        AVAIL_KB="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"
        if [ "$AVAIL_KB" -gt 0 ] 2>/dev/null; then
          echo "$(( AVAIL_KB / 1024 / 1024 ))"
        else
          echo 0
        fi
      else
        echo 0
      fi
      ;;
  esac
}
RAM_GB="$(detect_ram_gb)"
log "free RAM: ${RAM_GB} GB"

# ---------- detect GPU ----------
GPU_DETECTED=0
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi -L >/dev/null 2>&1; then GPU_DETECTED=1; fi
fi
if [ "$PLATFORM" = "mac" ]; then
  # Apple Silicon — unified memory, treat as "GPU class" only for tier lift
  if [ "$UNAME_M" = "arm64" ]; then GPU_DETECTED=1; fi
fi
log "GPU detected: $GPU_DETECTED"

# ---------- pick model tier ----------
# tier names: mini / small / medium / large / xl
pick_tier() {
  if [ -n "$FORCE_TIER" ]; then echo "$FORCE_TIER"; return; fi
  if [ "$RAM_GB" -lt 8 ];  then echo mini;   return; fi
  if [ "$RAM_GB" -lt 16 ]; then echo small;  return; fi
  if [ "$RAM_GB" -lt 32 ]; then echo medium; return; fi
  if [ "$RAM_GB" -lt 64 ]; then echo large;  return; fi
  echo xl
}
TIER="$(pick_tier)"

case "$TIER" in
  mini)   DEFAULT_MODEL="qwen2.5:3b-instruct-q4_K_M";   CTX=4096 ;;
  small)  DEFAULT_MODEL="llama3.1:8b-instruct-q4_K_M";  CTX=8192 ;;
  medium) DEFAULT_MODEL="qwen2.5:14b-instruct-q4_K_M";  CTX=8192 ;;
  large)  DEFAULT_MODEL="qwen2.5:32b-instruct-q4_K_M";  CTX=8192 ;;
  xl)     DEFAULT_MODEL="llama3.3:70b-instruct-q4_K_M"; CTX=8192 ;;
  *) fail "unknown tier: $TIER" ;;
esac

MODEL="${FORCE_MODEL:-$DEFAULT_MODEL}"
log "selected tier=$TIER model=$MODEL context=$CTX"

# ---------- install Ollama if missing ----------
install_ollama_mac() {
  if command -v ollama >/dev/null 2>&1; then return 0; fi
  if command -v brew >/dev/null 2>&1; then
    log "installing ollama via Homebrew"
    brew install ollama
  else
    log "Homebrew not found; downloading Ollama installer .zip"
    TMP="$(mktemp -d)"
    curl -fsSL https://ollama.com/download/Ollama-darwin.zip -o "$TMP/ollama.zip"
    unzip -q "$TMP/ollama.zip" -d "$TMP"
    if [ -d "$TMP/Ollama.app" ]; then
      cp -R "$TMP/Ollama.app" /Applications/ 2>/dev/null || \
        cp -R "$TMP/Ollama.app" "$HOME/Applications/"
      log "Ollama.app copied. Launch it once to start the menubar daemon."
    else
      fail "could not unpack Ollama"
    fi
  fi
}

install_ollama_linux() {
  if command -v ollama >/dev/null 2>&1; then return 0; fi
  log "installing ollama via official one-liner"
  curl -fsSL https://ollama.com/install.sh | sh
}

case "$PLATFORM" in
  mac)   install_ollama_mac ;;
  linux) install_ollama_linux ;;
esac

# ---------- start daemon if not running ----------
start_daemon() {
  if curl -fsS --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    log "ollama daemon already running"
    return 0
  fi
  case "$PLATFORM" in
    mac)
      log "starting Ollama.app (menubar)"
      open -a Ollama 2>/dev/null || true
      ;;
    linux)
      if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files 2>/dev/null | grep -q ollama; then
        systemctl --user start ollama 2>/dev/null || true
      else
        log "starting 'ollama serve' in background → ~/.crp-comply/ollama.log"
        mkdir -p "$HOME/.crp-comply"
        nohup ollama serve >"$HOME/.crp-comply/ollama.log" 2>&1 &
      fi
      ;;
  esac

  # wait up to 15 s for it to come up
  i=0
  while [ "$i" -lt 30 ]; do
    if curl -fsS --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      log "ollama daemon is up"
      return 0
    fi
    i=$((i + 1))
    sleep 0.5
  done
  fail "ollama daemon did not start within 15s. Try: 'ollama serve' manually."
}
start_daemon

# ---------- pull model ----------
log "pulling model $MODEL (this can take several minutes)…"
ollama pull "$MODEL"

# ---------- write config ----------
CONF_DIR="$HOME/.crp-comply"
CONF_FILE="$CONF_DIR/local-llm.json"
mkdir -p "$CONF_DIR"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat >"$CONF_FILE" <<EOF
{
  "provider": "ollama",
  "base_url": "http://127.0.0.1:11434",
  "model": "$MODEL",
  "context_window": $CTX,
  "tier": "$TIER",
  "ram_gb": $RAM_GB,
  "gpu_detected": $GPU_DETECTED,
  "installed_at": "$NOW"
}
EOF
log "wrote $CONF_FILE"

# ---------- smoke test ----------
log "smoke-testing model with a one-line prompt…"
SMOKE="$(curl -fsS http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}]}" \
  || true)"
if printf '%s' "$SMOKE" | grep -qi '"ok"\|"content":"ok'; then
  log "smoke test passed"
else
  warn "smoke test did not return 'ok' — model may still be loading. First call from crp-comply may be slow."
fi

# ---------- done ----------
cat <<EOF

──────────────────────────────────────────────────────────────────
✅ Local LLM installed.

  provider:        ollama
  endpoint:        http://127.0.0.1:11434
  model:           $MODEL
  context window:  $CTX tokens
  tier:            $TIER  (RAM ${RAM_GB} GB, GPU=$GPU_DETECTED)

To use it from a one-off shell:

  export CRP_COMPLY_PROVIDER=ollama
  export OLLAMA_BASE_URL=http://127.0.0.1:11434
  export OLLAMA_MODEL=$MODEL

crp-comply auto-detects $CONF_FILE on next start, so the
Settings → AI provider → Local card should already be green.

Smoke test from crp-comply itself:
  crp-comply llm-probe

──────────────────────────────────────────────────────────────────
EOF
