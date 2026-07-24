$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$venvPath = Join-Path $engineRoot "venv"
New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
  & python -m venv $venvPath
}
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip "yt-dlp>=2026.1"
if ($LASTEXITCODE -ne 0) { throw "L'installation de yt-dlp a échoué." }
& $pythonExe -m yt_dlp --version
if ($LASTEXITCODE -ne 0) { throw "La validation de yt-dlp a échoué." }
@{engine_id=$env:DUB_ENGINE_ID;python=$pythonExe;installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Encoding UTF8
