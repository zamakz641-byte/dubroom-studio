param(
  [Parameter(Mandatory = $true)][string]$Url,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][int64]$ExpectedSize,
  [int]$Connections = 16,
  [int]$CycleSeconds = 45,
  [int]$RpcPort = 6800
)

$ErrorActionPreference = "Stop"
$workspace = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$targetPath = [IO.Path]::GetFullPath($Target)
if (-not $targetPath.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar)) {
  throw "Download target must stay inside the workspace"
}
$targetRoot = Split-Path $targetPath -Parent
$targetName = Split-Path $targetPath -Leaf
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

$aria = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
  -Recurse -Filter "aria2c.exe" -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $aria) { throw "aria2c.exe is not installed" }

$rpcUrl = "http://127.0.0.1:$RpcPort/jsonrpc"
$startedAt = Get-Date
for ($cycle = 1; $cycle -le 80; $cycle++) {
  if (
    (Test-Path -LiteralPath $targetPath) -and
    (Get-Item -LiteralPath $targetPath).Length -eq $ExpectedSize -and
    -not (Test-Path -LiteralPath ($targetPath + ".aria2"))
  ) { break }

  $arguments = @(
    "--enable-rpc=true", "--rpc-listen-all=false", "--rpc-listen-port=$RpcPort",
    "--continue=true", "--max-connection-per-server=$Connections", "--split=$Connections",
    "--min-split-size=1M", "--file-allocation=none", "--auto-save-interval=5", "--max-tries=0",
    "--retry-wait=1", "--timeout=20", "--connect-timeout=10",
    "--summary-interval=0", "--console-log-level=warn",
    "--dir=.", "--out=$targetName", $Url
  )
  $process = Start-Process -FilePath $aria -ArgumentList $arguments `
    -WorkingDirectory $targetRoot -WindowStyle Hidden -PassThru
  $cycleDeadline = (Get-Date).AddSeconds($CycleSeconds)
  $lastCompleted = 0L
  while (-not $process.HasExited -and (Get-Date) -lt $cycleDeadline) {
    Start-Sleep -Seconds 5
    try {
      $body = @{jsonrpc="2.0";id="progress";method="aria2.tellActive";params=@()} |
        ConvertTo-Json -Compress
      $active = (Invoke-RestMethod -Method Post -Uri $rpcUrl -ContentType "application/json" -Body $body).result |
        Select-Object -First 1
      if ($active) {
        $lastCompleted = [int64]$active.completedLength
        $percent = [math]::Round(($lastCompleted / $ExpectedSize) * 100, 1)
        $speed = [math]::Round(([int64]$active.downloadSpeed / 1MB), 2)
        Write-Output "cycle=$cycle progress=$percent% speed=$speed MB/s"
      }
    } catch {
      # The RPC socket is briefly unavailable while aria2 starts or finishes.
    }
    $process.Refresh()
  }
  if (-not $process.HasExited) {
    $process.Kill()
    $process.WaitForExit()
  }
}

if (-not (Test-Path -LiteralPath $targetPath)) {
  throw "Download did not create $targetPath"
}
$actual = (Get-Item -LiteralPath $targetPath).Length
if ($actual -ne $ExpectedSize -or (Test-Path -LiteralPath ($targetPath + ".aria2"))) {
  throw "Download is incomplete: $actual / $ExpectedSize bytes"
}

[PSCustomObject]@{
  target = $targetPath
  bytes = $actual
  elapsed_seconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
  status = "verified"
} | ConvertTo-Json
