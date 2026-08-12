<#
.SYNOPSIS
    Bootstrap a local OpenAI-compatible LLM (via Ollama) for crp-comply.

.DESCRIPTION
    Detects RAM and GPU, installs Ollama (winget or official MSI),
    pulls the right-sized model, and writes %USERPROFILE%\.crp-comply\local-llm.json.

.PARAMETER Model
    Force a specific model identifier (e.g. 'llama3.1:8b-instruct-q4_K_M').

.PARAMETER Tier
    Force a tier: mini / small / medium / large / xl.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_local_llm.ps1
#>
[CmdletBinding()]
param(
    [string]$Model = "",
    [ValidateSet("mini","small","medium","large","xl","")]
    [string]$Tier  = ""
)

$ErrorActionPreference = "Stop"

function Write-Step($msg)  { Write-Host "[install-local-llm] $msg" -ForegroundColor Cyan }
function Write-Note($msg)  { Write-Host "[install-local-llm] $msg" -ForegroundColor DarkGray }
function Write-Warn2($msg) { Write-Host "[install-local-llm WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "[install-local-llm FAIL] $msg" -ForegroundColor Red; exit 1 }

# ---------- detect platform ----------
$osVer  = [System.Environment]::OSVersion.VersionString
$arch   = $env:PROCESSOR_ARCHITECTURE
Write-Step "platform=Windows arch=$arch ($osVer)"

# ---------- detect RAM (free GB) ----------
function Get-FreeRamGB {
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        # FreePhysicalMemory is in KB
        return [int]([math]::Floor($os.FreePhysicalMemory / 1024 / 1024))
    } catch {
        try {
            $tot = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
            return [int]([math]::Floor($tot / 1GB))
        } catch { return 0 }
    }
}
$ramGb = Get-FreeRamGB
Write-Step "free RAM: $ramGb GB"

# ---------- detect NVIDIA GPU ----------
$gpuDetected = 0
try {
    $gpus = Get-CimInstance Win32_VideoController -ErrorAction Stop
    foreach ($g in $gpus) {
        if ($g.Name -match 'NVIDIA|GeForce|RTX|Quadro|Tesla') { $gpuDetected = 1; break }
    }
} catch {}
Write-Step "GPU detected: $gpuDetected"

# ---------- pick tier ----------
function Get-Tier {
    if ($Tier) { return $Tier }
    if ($ramGb -lt 8)  { return "mini"   }
    if ($ramGb -lt 16) { return "small"  }
    if ($ramGb -lt 32) { return "medium" }
    if ($ramGb -lt 64) { return "large"  }
    return "xl"
}
$resolvedTier = Get-Tier
switch ($resolvedTier) {
    "mini"   { $defaultModel = "qwen2.5:3b-instruct-q4_K_M";   $ctx = 4096 }
    "small"  { $defaultModel = "llama3.1:8b-instruct-q4_K_M";  $ctx = 8192 }
    "medium" { $defaultModel = "qwen2.5:14b-instruct-q4_K_M";  $ctx = 8192 }
    "large"  { $defaultModel = "qwen2.5:32b-instruct-q4_K_M";  $ctx = 8192 }
    "xl"     { $defaultModel = "llama3.3:70b-instruct-q4_K_M"; $ctx = 8192 }
}
$resolvedModel = if ($Model) { $Model } else { $defaultModel }
Write-Step "selected tier=$resolvedTier model=$resolvedModel context=$ctx"

# ---------- install Ollama if missing ----------
function Test-OllamaInstalled {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

if (-not (Test-OllamaInstalled)) {
    Write-Step "Ollama not found — installing"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Note "via winget"
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Note "winget not present — downloading official installer"
        $tmp = New-TemporaryFile
        $exe = "$($tmp.FullName).exe"
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $exe
        Start-Process -FilePath $exe -ArgumentList "/SILENT" -Wait
        Remove-Item $exe -ErrorAction SilentlyContinue
    }

    # Refresh PATH for this session so 'ollama' becomes resolvable.
    $env:Path = "$env:Path;$env:LOCALAPPDATA\Programs\Ollama"
    if (-not (Test-OllamaInstalled)) {
        Write-Fail "Ollama install completed but 'ollama' is still not on PATH. Open a new shell and re-run."
    }
} else {
    Write-Note "Ollama is already installed"
}

# ---------- start daemon if not running ----------
function Test-OllamaUp {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri "http://127.0.0.1:11434/api/tags"
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (-not (Test-OllamaUp)) {
    Write-Step "starting ollama daemon"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    $tries = 0
    while (-not (Test-OllamaUp) -and $tries -lt 30) {
        Start-Sleep -Milliseconds 500
        $tries++
    }
    if (-not (Test-OllamaUp)) {
        Write-Fail "ollama daemon did not start within 15s. Try: 'ollama serve' in another terminal."
    }
}
Write-Step "ollama daemon is up"

# ---------- pull model ----------
Write-Step "pulling model $resolvedModel (several minutes possible)…"
& ollama pull $resolvedModel
if ($LASTEXITCODE -ne 0) { Write-Fail "ollama pull failed (exit $LASTEXITCODE)" }

# ---------- write config ----------
$confDir = Join-Path $env:USERPROFILE ".crp-comply"
$confFile = Join-Path $confDir "local-llm.json"
New-Item -ItemType Directory -Force -Path $confDir | Out-Null
$now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$conf = [ordered]@{
    provider       = "ollama"
    base_url       = "http://127.0.0.1:11434"
    model          = $resolvedModel
    context_window = $ctx
    tier           = $resolvedTier
    ram_gb         = $ramGb
    gpu_detected   = $gpuDetected
    installed_at   = $now
}
$conf | ConvertTo-Json -Depth 4 | Set-Content -Path $confFile -Encoding UTF8
Write-Step "wrote $confFile"

# ---------- smoke test ----------
Write-Step "smoke-testing model…"
try {
    $body = @{
        model    = $resolvedModel
        stream   = $false
        messages = @(@{ role = "user"; content = "Reply with the single word: ok" })
    } | ConvertTo-Json -Depth 4 -Compress
    $resp = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:11434/api/chat" -ContentType "application/json" -Body $body
    if ($resp.message.content -match "ok") {
        Write-Step "smoke test passed"
    } else {
        Write-Warn2 "smoke test did not return 'ok' — first crp-comply call may be slow as model loads."
    }
} catch {
    Write-Warn2 "smoke test failed: $_"
}

# ---------- done ----------
@"

──────────────────────────────────────────────────────────────────
✅ Local LLM installed.

  provider:        ollama
  endpoint:        http://127.0.0.1:11434
  model:           $resolvedModel
  context window:  $ctx tokens
  tier:            $resolvedTier  (RAM $ramGb GB, GPU=$gpuDetected)

To use it from this shell:
  `$env:CRP_COMPLY_PROVIDER = "ollama"
  `$env:OLLAMA_BASE_URL    = "http://127.0.0.1:11434"
  `$env:OLLAMA_MODEL       = "$resolvedModel"

Or persist for your user:
  setx CRP_COMPLY_PROVIDER "ollama"
  setx OLLAMA_BASE_URL    "http://127.0.0.1:11434"
  setx OLLAMA_MODEL       "$resolvedModel"

crp-comply auto-detects $confFile on next start, so the
Settings → AI provider → Local card should already be green.

Smoke test from crp-comply itself:
  crp-comply llm-probe
──────────────────────────────────────────────────────────────────

"@ | Write-Host
