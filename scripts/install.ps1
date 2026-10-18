# SPIKE installer for Windows (PowerShell 5.1 or 7), run from a source checkout:
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1                  # shows each command and asks first
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Yes             # runs every step without asking
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Yes -NoModel    # the same, without the model download
#
# It installs only what it names: pipx (if missing, for this user), the SPIKE app (pipx, isolated) and
# llama.cpp through winget (official package). It never asks for administrator rights and never downloads
# a model unless you accept that step (-NoModel leaves it out, ~2.7 GB).
# A step you accepted that fails stops it with exit 1. "Done." is printed only after `spike doctor --strict`
# passed: llama-server found and, unless the model was left out, a model on disk.
[CmdletBinding()]
param([switch]$Yes, [switch]$NoModel)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Have([string]$Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Fail([string]$Message) { Write-Host "`nerror: $Message" -ForegroundColor Red; exit 1 }

# Step "description" { command } -> prints the command, asks, runs it. Returns $true when it worked, $false when
# it failed and $null when the user skipped it.
function Step([string]$What, [scriptblock]$Command) {
    Write-Host "`n== $What"
    $shown = $Command.ToString().Trim().Replace('@pyArgs', '$($pyArgs -join '' '')')
    Write-Host "   > $($ExecutionContext.InvokeCommand.ExpandString($shown) -replace '\s+', ' ')"
    if (-not $Yes) {
        $answer = Read-Host '   Run it? [y/N]'
        if ($answer -notmatch '^[yY]') { Write-Host '   skipped'; return $null }
    }
    $global:LASTEXITCODE = 0
    try { & $Command | Out-Host } catch { Write-Host "   failed: $_" -ForegroundColor Yellow; return $false }
    if ($LASTEXITCODE -ne 0) { Write-Host "   failed (exit $LASTEXITCODE)" -ForegroundColor Yellow; return $false }
    return $true
}

Write-Host "SPIKE installer (Windows $([Environment]::OSVersion.Version), $env:PROCESSOR_ARCHITECTURE)"

# 1. Python 3.11+ (the py launcher first, then python on PATH)
$py = $null
foreach ($candidate in @(@('py', '-3'), @('python'))) {
    if (Have $candidate[0]) {
        $args0 = @($candidate | Select-Object -Skip 1)
        & $candidate[0] @args0 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $candidate; break }
    }
}
if (-not $py) { Fail 'Python 3.11 or newer is required: https://www.python.org/downloads/windows/' }
$pyExe = $py[0]; $pyArgs = @($py | Select-Object -Skip 1)
Write-Host "Python: $(& $pyExe @pyArgs --version)"

# 2. pipx (installs SPIKE in its own environment)
& $pyExe @pyArgs -m pipx --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    if (-not (Step 'Install pipx for this user' { & $pyExe @pyArgs -m pip install --user pipx })) { Fail 'pipx is required.' }
    Step "Add pipx's app folder to PATH" { & $pyExe @pyArgs -m pipx ensurepath } | Out-Null
}

# 3. Web app (built once from source; release packages will ship it prebuilt)
if (-not (Test-Path 'web\dist\index.html')) {
    if (-not (Have 'npm')) { Fail 'Node.js 18+ with npm is needed to build the web app: https://nodejs.org' }
    $built = Step 'Build the web app' { Push-Location web; try { npm ci; if ($LASTEXITCODE -eq 0) { npm run build } } finally { Pop-Location } }
    if (-not $built) { Fail 'the web app must be built before installing.' }
}

# 4. SPIKE itself
if (-not (Step 'Install SPIKE with pipx' { & $pyExe @pyArgs -m pipx install --force '.[docs,finance,data,motion]' })) { Fail 'SPIKE was not installed.' }
$binDir = (& $pyExe @pyArgs -m pipx environment --value PIPX_BIN_DIR 2>$null)
if (-not $binDir) { $binDir = Join-Path $env:USERPROFILE '.local\bin' }
$spike = @('spike.exe', 'spike') | ForEach-Object { Join-Path $binDir $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $spike) { $spike = 'spike' }

# 5. llama.cpp (local inference). Optional: SPIKE also works with external providers only.
if ((Have 'llama-server') -or $env:SPIKE_LLAMA_SERVER) {
    Write-Host "`nllama-server: $(if ($env:SPIKE_LLAMA_SERVER) { $env:SPIKE_LLAMA_SERVER } else { (Get-Command llama-server).Source })"
} elseif (Have 'winget') {
    $installed = Step 'Install llama.cpp with winget (official package)' {
        winget install llama.cpp --accept-source-agreements --accept-package-agreements
    }
    if ($null -ne $installed) {
        # winget puts llama-server on the user's PATH, which this session only sees after reading it again
        $known = $env:Path -split ';'
        $added = foreach ($scope in 'Machine', 'User') {
            [Environment]::GetEnvironmentVariable('Path', $scope) -split ';'
        }
        $env:Path = (@($env:Path) + @($added | Where-Object { $_ -and ($known -notcontains $_) })) -join ';'
        # a non-zero exit can also mean "already installed", so what counts is whether llama-server is there now
        if (-not $installed -and -not (Have 'llama-server')) {
            Fail 'llama.cpp was not installed (see above). Fix that and re-run, or set SPIKE_LLAMA_SERVER.'
        }
        Write-Host '   Open a new terminal afterwards so llama-server is on PATH there too.'
    }
} else {
    Write-Host @'

llama-server was not found. Install llama.cpp with one of its official methods, then run 'spike doctor':
  winget install llama.cpp
  conda install -c conda-forge llama.cpp
  prebuilt binaries: https://github.com/ggml-org/llama.cpp/releases
or point SPIKE at an existing binary with $env:SPIKE_LLAMA_SERVER = 'C:\path\to\llama-server.exe'
'@
}

# 6. The base model (~2.7 GB, license and SHA-256 checked); -NoModel leaves it out without asking
if ($NoModel) {
    Write-Host "`nSkipping the model download (-NoModel)."
} else {
    $pulled = Step 'Download the base model Qwen3.5-4B (Q4_K_M, ~2.7 GB)' { & $spike models pull qwen3.5-4b }
    if ($pulled -eq $false) {
        Fail "the model download failed (see above). Re-run the installer, or run: $spike models pull qwen3.5-4b"
    }
}

# 7. Check the result: shows the memory plan, and fails when llama-server (or the model) is missing
# (a model the user declined, like -NoModel, is not asked for)
if ($NoModel -or $null -eq $pulled) {
    $checked = Step 'Check the install' { & $spike doctor --strict --no-model-check }
} else {
    $checked = Step 'Check the install' { & $spike doctor --strict }
}
if ($checked -eq $false) { Fail "'spike doctor --strict' found a missing part (see above); SPIKE itself is installed." }

Write-Host "`nDone. Start SPIKE with:  $spike serve --open"
if (-not (($env:Path -split ';') -contains $binDir)) {
    Write-Host "Open a new terminal (or add $binDir to PATH) to use 'spike' directly."
}
