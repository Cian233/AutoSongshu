param(
    [switch]$SkipUvSync,
    [switch]$SkipPlaywrightInstall,
    [switch]$SkipVendorBootstrap,
    [switch]$ForceVendorRefresh,
    [switch]$SkipStatusChecks,
    [switch]$SkipNmapInstall,
    [switch]$SkipPythonRuntimeCheck,
    [switch]$SkipPythonRuntimeRepair,
    [string]$SqlmapRepo = "https://github.com/sqlmapproject/sqlmap.git",
    [string]$SqlmapRef = "master",
    [string]$DirsearchRepo = "https://github.com/maurosoria/dirsearch.git",
    [string]$DirsearchRef = "master",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[AutoSongshu:init] $Message" -ForegroundColor Green
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ""
    )

    $renderedArgs = if ($Arguments.Count -gt 0) { $Arguments -join " " } else { "" }
    Write-Host "Command: $FilePath $renderedArgs" -ForegroundColor DarkGray
    if ($DryRun) {
        return
    }

    if ($WorkingDirectory) {
        Push-Location -LiteralPath $WorkingDirectory
    }
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $renderedArgs"
        }
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Test-PythonRuntimeHealth {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [ref]$FailureOutput
    )

    Write-Step "Running Python runtime binary self-check..."
    if ($DryRun) {
        Write-Host "Command: uv run python <python-runtime-health-check-script>" -ForegroundColor DarkGray
        return $true
    }

    $healthScriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("autosongshu-runtime-health-{0}.py" -f ([guid]::NewGuid().ToString("N")))
    $healthScriptContent = @'
import importlib
import os

imports = ["numpy"]
if os.name == "nt":
    imports.extend(["pywintypes", "pythoncom"])

for name in imports:
    importlib.import_module(name)

print("runtime-ok")
'@
    Set-Content -LiteralPath $healthScriptPath -Value $healthScriptContent -Encoding UTF8

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    $exitCode = 0
    $combinedOutput = ""
    Push-Location -LiteralPath $ProjectRoot
    try {
        $process = Start-Process -FilePath "uv" `
            -ArgumentList @("run", "python", $healthScriptPath) `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile

        $exitCode = $process.ExitCode
        $stdoutContent = if (Test-Path -LiteralPath $stdoutFile) {
            Get-Content -LiteralPath $stdoutFile -Raw -ErrorAction SilentlyContinue
        }
        else {
            ""
        }
        $stderrContent = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        }
        else {
            ""
        }
        $combinedOutput = ($stdoutContent + $stderrContent).Trim()
    }
    finally {
        if (Test-Path -LiteralPath $stdoutFile) {
            Remove-Item -LiteralPath $stdoutFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $stderrFile) {
            Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $healthScriptPath) {
            Remove-Item -LiteralPath $healthScriptPath -Force -ErrorAction SilentlyContinue
        }
        Pop-Location
    }

    if ($exitCode -eq 0) {
        return $true
    }

    if ($FailureOutput) {
        $FailureOutput.Value = $combinedOutput
    }
    return $false
}

function Repair-PythonRuntimeBinaryDeps {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    if ($SkipPythonRuntimeRepair) {
        Write-Warning "Python runtime auto-repair is disabled by -SkipPythonRuntimeRepair."
        return $false
    }

    $args = @("sync", "--reinstall-package", "numpy")
    if ($env:OS -eq "Windows_NT") {
        $args += @("--reinstall-package", "pywin32")
    }

    Write-Step "Attempting Python runtime binary repair via uv..."
    Invoke-External -FilePath "uv" -Arguments $args -WorkingDirectory $ProjectRoot
    return $true
}

function Test-VendorReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetDir,
        [Parameter(Mandatory = $true)]
        [string[]]$RequiredRelativePaths
    )

    if (-not (Test-Path -LiteralPath $TargetDir)) {
        return $false
    }

    foreach ($relativePath in $RequiredRelativePaths) {
        $fullPath = Join-Path $TargetDir $relativePath
        if (-not (Test-Path -LiteralPath $fullPath)) {
            return $false
        }
    }
    return $true
}

function Sync-GitVendor {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$RepoUrl,
        [Parameter(Mandatory = $true)]
        [string]$Ref,
        [Parameter(Mandatory = $true)]
        [string]$TargetDir,
        [Parameter(Mandatory = $true)]
        [string[]]$RequiredRelativePaths
    )

    if ($ForceVendorRefresh -and (Test-Path -LiteralPath $TargetDir)) {
        Write-Step "Force refresh enabled. Removing existing $Name vendor tree..."
        if (-not $DryRun) {
            Remove-Item -LiteralPath $TargetDir -Recurse -Force
        }
    }

    if (Test-VendorReady -TargetDir $TargetDir -RequiredRelativePaths $RequiredRelativePaths) {
        Write-Step "$Name vendor tree already available."
        return
    }

    if (Test-Path -LiteralPath $TargetDir) {
        Write-Step "$Name vendor tree is incomplete. Rebuilding..."
        if (-not $DryRun) {
            Remove-Item -LiteralPath $TargetDir -Recurse -Force
        }
    }

    $parentDir = Split-Path -Parent $TargetDir
    if (-not (Test-Path -LiteralPath $parentDir)) {
        if (-not $DryRun) {
            New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
        }
    }

    Write-Step "Cloning $Name ($Ref) from $RepoUrl ..."
    if (-not $DryRun) {
        & git clone --depth 1 --branch $Ref $RepoUrl $TargetDir
        if ($LASTEXITCODE -ne 0) {
            if (Test-Path -LiteralPath $TargetDir) {
                Remove-Item -LiteralPath $TargetDir -Recurse -Force
            }
            Write-Step "Branch clone failed for $Name. Falling back to detached ref checkout..."
            & git clone --depth 1 $RepoUrl $TargetDir
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to clone $Name from $RepoUrl"
            }
            Invoke-External -FilePath "git" -Arguments @("fetch", "--depth", "1", "origin", $Ref) -WorkingDirectory $TargetDir
            Invoke-External -FilePath "git" -Arguments @("-c", "advice.detachedHead=false", "checkout", "--detach", "FETCH_HEAD") -WorkingDirectory $TargetDir
        }
    }
    else {
        Write-Host "Command: git clone --depth 1 --branch $Ref $RepoUrl $TargetDir" -ForegroundColor DarkGray
    }

    if (-not $DryRun) {
        if (-not (Test-VendorReady -TargetDir $TargetDir -RequiredRelativePaths $RequiredRelativePaths)) {
            throw "$Name vendor tree is still incomplete after bootstrap: $TargetDir"
        }
    }
    Write-Step "$Name vendor tree is ready."
}

function Resolve-NmapAvailability {
    param([string]$ProjectRoot)

    $vendorBinary = if ($env:OS -eq "Windows_NT") {
        Join-Path $ProjectRoot "skills\nmap-recon\vendor\nmap\nmap.exe"
    }
    else {
        Join-Path $ProjectRoot "skills/nmap-recon/vendor/nmap/nmap"
    }
    if (Test-Path -LiteralPath $vendorBinary) {
        return @{ Available = $true; Source = "bundled"; Path = $vendorBinary }
    }

    $systemNmap = Get-Command nmap -ErrorAction SilentlyContinue
    if ($systemNmap) {
        return @{ Available = $true; Source = "system"; Path = $systemNmap.Source }
    }

    return @{ Available = $false; Source = "missing"; Path = "" }
}

function Ensure-NmapAvailable {
    param([string]$ProjectRoot)

    $status = Resolve-NmapAvailability -ProjectRoot $ProjectRoot
    if ($status.Available) {
        Write-Step "Nmap is available via $($status.Source): $($status.Path)"
        return
    }

    if ($SkipNmapInstall) {
        Write-Warning "Nmap is not available. nmap-recon skill will remain unavailable until you install Nmap."
        return
    }

    if ($env:OS -ne "Windows_NT") {
        Write-Warning "Nmap is not available and auto-install is only implemented for Windows. Please install nmap with your package manager."
        return
    }

    if (-not (Test-CommandExists "winget")) {
        Write-Warning "Nmap is not available and winget is not installed. Please install Nmap manually."
        return
    }

    Write-Step "Attempting to install Nmap via winget (Insecure.Nmap)..."
    Invoke-External -FilePath "winget" -Arguments @(
        "install",
        "--id", "Insecure.Nmap",
        "-e",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent"
    )

    $after = Resolve-NmapAvailability -ProjectRoot $ProjectRoot
    if ($after.Available) {
        Write-Step "Nmap installation succeeded: $($after.Path)"
    }
    else {
        Write-Warning "Nmap install attempted but binary is still not available. nmap-recon skill may be unavailable."
    }
}

function Invoke-StatusScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$RelativeScriptPath
    )

    $scriptPath = Join-Path $ProjectRoot $RelativeScriptPath
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "Status script not found for ${Name}: $scriptPath"
    }

    Write-Step "Running $Name status check..."
    if ($DryRun) {
        Write-Host "Command: uv run python $scriptPath" -ForegroundColor DarkGray
        return $null
    }

    $rawOutput = & uv run python $scriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "$Name status script failed with exit code $LASTEXITCODE"
    }

    try {
        return ($rawOutput | Out-String | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        throw "Failed to parse $Name status JSON output: $($_.Exception.Message)"
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

if (-not (Test-CommandExists "uv")) {
    throw "uv is not installed or not available in PATH."
}
if (-not (Test-CommandExists "git")) {
    throw "git is not installed or not available in PATH."
}

Set-Location -LiteralPath $ProjectRoot
Write-Step "Project root: $ProjectRoot"

if (-not $SkipUvSync) {
    Write-Step "Installing Python dependencies with uv sync..."
    # 强制设置 UV_LINK_MODE=copy 以防止跨盘符/文件系统限制导致硬链接创建失败和卡死
    $env:UV_LINK_MODE = "copy"
    Invoke-External -FilePath "uv" -Arguments @("sync")
}
else {
    Write-Step "Skipping uv sync."
}

if (-not $SkipPythonRuntimeCheck) {
    $runtimeFailure = ""
    if (Test-PythonRuntimeHealth -ProjectRoot $ProjectRoot -FailureOutput ([ref]$runtimeFailure)) {
        Write-Step "Python runtime binary self-check passed."
    }
    else {
        Write-Warning "Python runtime binary self-check failed. This commonly indicates a broken numpy/pywin32 wheel install."
        if ($runtimeFailure) {
            Write-Warning $runtimeFailure
        }

        $repaired = Repair-PythonRuntimeBinaryDeps -ProjectRoot $ProjectRoot
        if (-not $repaired) {
            throw "Python runtime self-check failed and auto-repair was not performed."
        }

        $runtimeFailureAfterRepair = ""
        if (-not (Test-PythonRuntimeHealth -ProjectRoot $ProjectRoot -FailureOutput ([ref]$runtimeFailureAfterRepair))) {
            if ($runtimeFailureAfterRepair) {
                throw "Python runtime self-check still failing after repair.`n$runtimeFailureAfterRepair"
            }
            throw "Python runtime self-check still failing after repair."
        }
        Write-Step "Python runtime binary self-check passed after automatic repair."
    }
}
else {
    Write-Step "Skipping Python runtime binary self-check."
}

if (-not $SkipPlaywrightInstall) {
    Write-Step "Ensuring Playwright Chromium is installed..."
    Invoke-External -FilePath "uv" -Arguments @("run", "playwright", "install", "chromium")
}
else {
    Write-Step "Skipping Playwright install."
}

if (-not $SkipVendorBootstrap) {
    Sync-GitVendor `
        -Name "sqlmap" `
        -RepoUrl $SqlmapRepo `
        -Ref $SqlmapRef `
        -TargetDir (Join-Path $ProjectRoot "skills\sqlmap-sqli\vendor\sqlmap") `
        -RequiredRelativePaths @("sqlmap.py", "sqlmap.conf", "lib\core\settings.py")

    Sync-GitVendor `
        -Name "dirsearch" `
        -RepoUrl $DirsearchRepo `
        -Ref $DirsearchRef `
        -TargetDir (Join-Path $ProjectRoot "skills\dirsearch-recon\vendor\dirsearch") `
        -RequiredRelativePaths @("dirsearch.py", "config.ini", "db")
}
else {
    Write-Step "Skipping vendor bootstrap."
}

Ensure-NmapAvailable -ProjectRoot $ProjectRoot

if (-not $SkipStatusChecks) {
    $sqlmapStatus = Invoke-StatusScript -ProjectRoot $ProjectRoot -Name "sqlmap-sqli" -RelativeScriptPath "skills\sqlmap-sqli\scripts\sqlmap_status.py"
    if ($sqlmapStatus -and -not $sqlmapStatus.available) {
        throw "sqlmap-sqli status check failed: bundled source is not available."
    }

    $dirsearchStatus = Invoke-StatusScript -ProjectRoot $ProjectRoot -Name "dirsearch-recon" -RelativeScriptPath "skills\dirsearch-recon\scripts\dirsearch_status.py"
    if ($dirsearchStatus) {
        if (-not $dirsearchStatus.available) {
            throw "dirsearch-recon status check failed: bundled source is not available."
        }
        if (-not $dirsearchStatus.dependency_check.required_available) {
            $missing = ($dirsearchStatus.dependency_check.missing_required -join ", ")
            throw "dirsearch-recon dependencies are missing: $missing"
        }
    }

    $nmapStatus = Invoke-StatusScript -ProjectRoot $ProjectRoot -Name "nmap-recon" -RelativeScriptPath "skills\nmap-recon\scripts\nmap_status.py"
    if ($nmapStatus -and -not $nmapStatus.available) {
        Write-Warning "nmap-recon status: nmap binary is missing. sqlmap/dirsearch examples are still available."
    }
    elseif ($nmapStatus) {
        Write-Step "nmap-recon status check passed."
    }
}
else {
    Write-Step "Skipping status checks."
}

Write-Step "Initializing sandbox environment..."
$sandboxInitScriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("autosongshu-sandbox-init-{0}.py" -f ([guid]::NewGuid().ToString("N")))
$sandboxInitScriptContent = @'
from autosongshu_agent.config import load_config, ScopePolicy
from autosongshu_agent.sandbox import PythonSandbox
from autosongshu_agent.artifacts import ArtifactStore
import tempfile
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")

try:
    print("Loading config...")
    config = load_config("configs/pentest.example.yaml")
    root = tempfile.mkdtemp()
    artifacts = ArtifactStore(str(root), "init")
    
    print(f"Creating sandbox instance...")
    sandbox = PythonSandbox(config.sandbox, ScopePolicy("http://localhost", []), artifacts, "init", "auth")
    
    print("Bootstrapping sandbox environment (this may take a minute or two to install packages)...")
    sandbox._ensure_bootstrapped()
    
    print("Sandbox bootstrapped successfully.")
except Exception as e:
    print(f"Failed to bootstrap sandbox: {e}")
    sys.exit(1)
'@
Set-Content -LiteralPath $sandboxInitScriptPath -Value $sandboxInitScriptContent -Encoding UTF8
Invoke-External -FilePath "uv" -Arguments @("run", "python", "-u", $sandboxInitScriptPath)

Write-Step "Build and initialization complete!"
Write-Host "Next step:" -ForegroundColor Cyan
Write-Host "  .\scripts\start-autosongshu.ps1" -ForegroundColor Cyan
