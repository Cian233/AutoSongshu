param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$SkipSync,
    [switch]$SkipBrowserInstall,
    [switch]$SkipInitBuild,
    [switch]$SkipInitVendorBootstrap,
    [switch]$ForceInitVendorRefresh,
    [switch]$SkipInitStatusChecks,
    [switch]$SkipInitPythonRuntimeCheck,
    [switch]$SkipInitPythonRuntimeRepair,
    [switch]$SkipFrontendBuild,
    [switch]$FrontendDev,
    [int]$FrontendDevPort = 5173,
    [switch]$LaunchCdpBrowser,
    [ValidateSet("chrome", "edge")]
    [string]$CdpBrowser = "chrome",
    [int]$CdpPort = 9222,
    [string]$CdpUrl = "",
    [switch]$NoOpenBrowser,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[AutoSongshu] $Message" -ForegroundColor Green
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-ChromiumInstalled {
    $roots = @()

    if ($env:PLAYWRIGHT_BROWSERS_PATH -and $env:PLAYWRIGHT_BROWSERS_PATH -ne "0") {
        $roots += $env:PLAYWRIGHT_BROWSERS_PATH
    }
    if ($env:LOCALAPPDATA) {
        $roots += (Join-Path $env:LOCALAPPDATA "ms-playwright")
    }

    foreach ($root in $roots | Select-Object -Unique) {
        if (-not (Test-Path $root)) {
            continue
        }
        $match = Get-ChildItem -Path $root -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($match) {
            return $true
        }
    }

    return $false
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $false
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $separatorIndex = $line.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $name = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()

        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        Set-Item -Path "Env:$name" -Value $value
    }

    return $true
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$CdpScriptPath = Join-Path $ScriptDir "start-cdp-browser.ps1"
$InitBuildScriptPath = Join-Path $ScriptDir "init-build.ps1"
$DisplayHost = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
$ConsoleUrl = "http://${DisplayHost}:$Port"

if (-not (Test-CommandExists "uv")) {
    throw "uv is not installed or not available in PATH."
}

Set-Location -LiteralPath $ProjectRoot

$EnvFile = Join-Path $ProjectRoot ".env"
if (Import-DotEnv -Path $EnvFile) {
    Write-Step "Loaded environment from $EnvFile"
}

Write-Step "Project root: $ProjectRoot"
Write-Step "Web console URL: $ConsoleUrl"
$InitBuildExecuted = $false

if ($FrontendDev) {
    Write-Step "Frontend dev mode enabled. Skipping production frontend build."
    if (-not $SkipFrontendBuild) {
        $SkipFrontendBuild = $true
    }
}

if (-not $SkipInitBuild) {
    if (-not (Test-Path -LiteralPath $InitBuildScriptPath)) {
        throw "Init build script not found: $InitBuildScriptPath"
    }

    Write-Step "Running startup preflight checks..."
    $initArgs = @(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $InitBuildScriptPath
    )
    if ($SkipSync) {
        $initArgs += "-SkipUvSync"
    }
    if ($SkipBrowserInstall) {
        $initArgs += "-SkipPlaywrightInstall"
    }
    if ($SkipInitVendorBootstrap) {
        $initArgs += "-SkipVendorBootstrap"
    }
    if ($ForceInitVendorRefresh) {
        $initArgs += "-ForceVendorRefresh"
    }
    if ($SkipInitStatusChecks) {
        $initArgs += "-SkipStatusChecks"
    }
    if ($SkipInitPythonRuntimeCheck) {
        $initArgs += "-SkipPythonRuntimeCheck"
    }
    if ($SkipInitPythonRuntimeRepair) {
        $initArgs += "-SkipPythonRuntimeRepair"
    }
    if ($SkipFrontendBuild) {
        $initArgs += "-SkipFrontendBuild"
    }
    if ($DryRun) {
        $initArgs += "-DryRun"
    }

    Write-Host "Command: powershell.exe $($initArgs -join ' ')" -ForegroundColor DarkGray
    if (-not $DryRun) {
        & powershell.exe @initArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Startup preflight failed with exit code $LASTEXITCODE"
        }
    }
    $InitBuildExecuted = $true
}
else {
    Write-Step "Skipping startup preflight checks."
}

if (-not $SkipSync) {
    if ($InitBuildExecuted) {
        Write-Step "uv sync already handled by startup preflight."
    }
    else {
        Write-Step "Running uv sync..."
        if (-not $DryRun) {
            uv sync --link-mode=copy
        }
    }
}

if (-not $SkipBrowserInstall) {
    if ($InitBuildExecuted) {
        Write-Step "Playwright Chromium check/install already handled by startup preflight."
    }
    else {
        if (Test-ChromiumInstalled) {
            Write-Step "Playwright Chromium already installed. Skipping install."
        }
        else {
            Write-Step "Installing Playwright Chromium..."
            if (-not $DryRun) {
                uv run playwright install chromium
            }
        }
    }
}

if ($LaunchCdpBrowser) {
    if (-not (Test-Path $CdpScriptPath)) {
        throw "CDP browser starter script not found: $CdpScriptPath"
    }

    Write-Step "Starting CDP browser ($CdpBrowser) on port $CdpPort..."
    $cdpCommandParts = @(
        "& '$CdpScriptPath'",
        "-Browser $CdpBrowser",
        "-Port $CdpPort"
    )
    if ($CdpUrl) {
        $cdpCommandParts += "-Url '$CdpUrl'"
    }
    Write-Host ("Command: " + ($cdpCommandParts -join " ")) -ForegroundColor DarkGray

    if (-not $DryRun) {
        $cdpParams = @{
            Browser = $CdpBrowser
            Port = $CdpPort
        }
        if ($CdpUrl) {
            $cdpParams["Url"] = $CdpUrl
        }
        try {
            & $CdpScriptPath @cdpParams
        }
        catch {
            Write-Warning "Failed to start CDP browser: $($_.Exception.Message)"
            Write-Warning "The web console will still start. Browser tools can fall back to local Playwright Chromium."
        }
        Start-Sleep -Milliseconds 800
    }
}

$ServerCommand = "Set-Location -LiteralPath '$ProjectRoot'; uv run autosongshu-web --host $BindHost --port $Port"
if ($Reload) {
    $ServerCommand += " --reload"
}

Write-Step "Starting FastAPI web console..."
Write-Host "Command: $ServerCommand" -ForegroundColor DarkGray

if ($DryRun) {
    Write-Step "DryRun mode enabled. Nothing started."
    exit 0
}

Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    $ServerCommand
) | Out-Null

Start-Sleep -Seconds 2

# ── Frontend dev server (optional) ──────────────────────────────────
$FrontendDir = Join-Path $ProjectRoot "frontend"
if ($FrontendDev -and (Test-Path -LiteralPath (Join-Path $FrontendDir "package.json"))) {
    if (-not (Test-CommandExists "node") -or -not (Test-CommandExists "npm")) {
        Write-Warning "Node.js/npm not found. Cannot start frontend dev server."
    }
    else {
        $FrontendDevUrl = "http://localhost:$FrontendDevPort"
        Write-Step "Starting Vite frontend dev server on port $FrontendDevPort..."
        $FrontendDevCommand = "Set-Location -LiteralPath '$FrontendDir'; npm run dev -- --port $FrontendDevPort"
        Write-Host "Command: $FrontendDevCommand" -ForegroundColor DarkGray

        Start-Process powershell.exe -ArgumentList @(
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            $FrontendDevCommand
        ) | Out-Null

        Start-Sleep -Seconds 2
        Write-Step "Frontend dev server running at: $FrontendDevUrl"
        Write-Host "  The dev server proxies API requests to the FastAPI backend." -ForegroundColor DarkGray
    }
}
elseif ($FrontendDev) {
    Write-Warning "-FrontendDev was specified but frontend/package.json not found. Skipping."
}

if (-not $NoOpenBrowser) {
    Write-Step "Opening browser..."
    $OpenUrl = if ($FrontendDev) { "http://localhost:$FrontendDevPort" } else { $ConsoleUrl }
    Start-Process $OpenUrl | Out-Null
}

Write-Step "Done. If the browser did not open automatically, visit: $ConsoleUrl"
