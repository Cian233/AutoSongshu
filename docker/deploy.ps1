# AutoSongshu Docker Deployment Script (Windows)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = Split-Path -Parent $scriptRoot

# Check if .env exists
if (-not (Test-Path "$projectRoot\.env")) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Cyan
    Copy-Item "$projectRoot\.env.example" "$projectRoot\.env"
    Write-Host "WARNING: Please edit .env and set your AUTOSONGSHU_MODEL_API_KEY and other settings!" -ForegroundColor Yellow
}

# Create necessary directories
$dirs = @("data", "artifacts", "configs", "skills")
foreach ($dir in $dirs) {
    if (-not (Test-Path "$projectRoot\$dir")) {
        Write-Host "Creating $dir directory..." -ForegroundColor Cyan
        New-Item -ItemType Directory -Path "$projectRoot\$dir" | Out-Null
    }
}

# Run docker-compose
Write-Host "Starting AutoSongshu via Docker Compose..." -ForegroundColor Green
Set-Location $scriptRoot
docker-compose up --build -d

Write-Host "`nAutoSongshu is starting!" -ForegroundColor Green
Write-Host "You can access the Web UI at: http://localhost:8000" -ForegroundColor Cyan
Write-Host "To view logs, run: docker-compose logs -f" -ForegroundColor Gray
