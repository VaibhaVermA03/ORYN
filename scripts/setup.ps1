# ORYN local setup for Windows PowerShell. Idempotent: never overwrites an existing .env.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Need($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Missing prerequisite: $cmd ($hint)" }
}
Need 'python' 'Python 3.12+ from https://www.python.org/downloads/ (tick "Add to PATH")'
Need 'node' 'Node.js 22+ from https://nodejs.org/'
Need 'npm' 'comes with Node.js'

python -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }

Write-Host '==> Backend: virtualenv and dependencies'
Set-Location "$Root\backend"
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\pip.exe install -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  $secret = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
  $content = Get-Content .env -Raw
  $regex = [regex]'APP_SECRET=\r?\n'
  $content = $regex.Replace($content, "APP_SECRET=$secret`n", 1)
  Set-Content .env -Value $content -NoNewline
  Write-Host 'Created backend\.env with a freshly generated APP_SECRET.'
  Write-Host 'Fill in DATABASE_URL, OPENAI_API_KEY, PINECONE_API_KEY, COHERE_API_KEY (and Google OAuth if wanted).'
} else {
  Write-Host 'backend\.env already exists; left untouched.'
}

Write-Host '==> Frontend: dependencies'
Set-Location "$Root\frontend"
npm ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }

Write-Host @'

Setup finished. Next:
  1. Edit backend\.env (database + provider keys).
  2. cd backend; .\.venv\Scripts\Activate.ps1; alembic upgrade head
  3. Start the API:      uvicorn app.main:app --reload --port 8000
  4. Start the frontend: cd frontend; npm run dev     -> http://localhost:5173
See README.md and docs\ for details.
'@
