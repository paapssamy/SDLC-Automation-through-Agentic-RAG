# One-command demo start: database -> data -> app.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt
}
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

docker compose up -d
Write-Host "Waiting for PostgreSQL..."
for ($i = 0; $i -lt 30; $i++) {
    docker exec sdlc_rag_db pg_isready -U sdlc -d sdlc_rag *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 2
}

.\.venv\Scripts\python scripts\demo_setup.py --reset --kb
.\.venv\Scripts\streamlit run app\ui\Home.py
