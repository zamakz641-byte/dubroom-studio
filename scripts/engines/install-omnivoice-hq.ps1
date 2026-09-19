$ErrorActionPreference = "Stop"
$runner = $env:DUB_BASE_PYTHON
if ([string]::IsNullOrWhiteSpace($runner)) { $runner = "python" }
$modelRoot = $env:DUB_ENGINE_MODELS
if ([string]::IsNullOrWhiteSpace($modelRoot)) { throw "DUB_ENGINE_MODELS missing" }
$projectRoot = Split-Path (Split-Path $modelRoot -Parent) -Parent
$helper = Join-Path $PSScriptRoot "install-omnivoice-runtime.py"
& $runner $helper --root $projectRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
