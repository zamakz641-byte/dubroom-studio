$ErrorActionPreference = "Stop"

function Set-DubProgress {
  param([int]$Progress, [string]$Message, [string]$Phase = "install")
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  $payload = @{status=$status;progress=$Progress;message=$Message;phase=$Phase;log_path=$env:DUB_ENGINE_LOG;updated_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
  Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Value $payload -Encoding UTF8
}

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
$sourceRoot = Join-Path $engineRoot "bandit-v2"
$modelPath = Join-Path $modelRoot "bandit-v2-dnr3-multilingual.ckpt"
New-Item -ItemType Directory -Path $engineRoot,$modelRoot,$env:DUB_ENGINE_CACHE -Force | Out-Null

Set-DubProgress 18 "Installation du séparateur cinéma spécialisé" "runtime"
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "src\models\bandit\bandit.py"))) {
  & git clone --depth 1 https://github.com/kwatcharasupat/bandit-v2.git $sourceRoot
  if ($LASTEXITCODE -ne 0) { throw "Le code Bandit v2 n'a pas pu être téléchargé." }
}

if (-not (Test-Path -LiteralPath $modelPath)) {
  Set-DubProgress 42 "Téléchargement unique du modèle cinéma multilingue" "download"
  & curl.exe -L --fail --retry 3 -C - -o $modelPath "https://zenodo.org/records/12701995/files/checkpoint-multi.ckpt?download=1"
  if ($LASTEXITCODE -ne 0) { throw "Le modèle Bandit cinéma n'a pas pu être téléchargé." }
}

Set-DubProgress 94 "Validation des fichiers Bandit Cinéma" "validate"
if ((Get-Item -LiteralPath $modelPath).Length -lt 400MB) { throw "Le modèle Bandit téléchargé est incomplet." }
$ready = @{
  engine_id = $env:DUB_ENGINE_ID
  model_path = $modelPath
  source_path = $sourceRoot
  shared_torch_provider = "tts-omnivoice-hq"
  device = "cuda"
  installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
Set-DubProgress 100 "Bandit Cinéma est prêt" "complete"
