param(
    [ValidateSet("chrome", "edge")]
    [string]$Browser = "chrome",

    [int]$Port = 9222,

    [string]$Url = "",

    [string]$UserDataDir = "$env:TEMP\autosongshu-cdp-$Browser-$Port"
)

function Resolve-BrowserPath {
    param([string]$Name)

    $candidates = switch ($Name) {
        "chrome" {
            @(
                "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
                "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
            )
        }
        "edge" {
            @(
                "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
                "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
                "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe"
            )
        }
    }

    return $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

$browserPath = Resolve-BrowserPath -Name $Browser
if (-not $browserPath) {
    throw "Unable to locate $Browser. Please install it or edit scripts/start-cdp-browser.ps1."
}

New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null

$arguments = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$UserDataDir",
    "--no-first-run",
    "--no-default-browser-check"
)

if ($Url) {
    $arguments += $Url
}

Start-Process -FilePath $browserPath -ArgumentList $arguments | Out-Null

Write-Host "Started $Browser with CDP on port $Port"
Write-Host "User data dir: $UserDataDir"
if ($Url) {
    Write-Host "Initial URL: $Url"
}
