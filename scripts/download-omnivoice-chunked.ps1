param(
  [string]$WorkspaceRoot = (Split-Path $PSScriptRoot -Parent),
  [int]$MainParts = 12,
  [int]$CodecParts = 4
)

$ErrorActionPreference = "Stop"
$workspace = [IO.Path]::GetFullPath($WorkspaceRoot)
$downloadRoot = [IO.Path]::GetFullPath(
  (Join-Path $workspace ("data\temp\omnivoice-download-" + [guid]::NewGuid().ToString("N")))
)
$safeTempRoot = [IO.Path]::GetFullPath((Join-Path $workspace "data\temp"))
if (-not $downloadRoot.StartsWith($safeTempRoot + [IO.Path]::DirectorySeparatorChar)) {
  throw "Unsafe OmniVoice temporary download path"
}

$specs = @(
  @{
    Name = "main"
    Size = [int64]2450344112
    Parts = $MainParts
    Url = "https://huggingface.co/k2-fsa/OmniVoice/resolve/main/model.safetensors?download=true"
    Target = Join-Path $workspace "models\tts-omnivoice-0.6b\model\model.safetensors"
  },
  @{
    Name = "codec"
    Size = [int64]805600772
    Parts = $CodecParts
    Url = "https://huggingface.co/k2-fsa/OmniVoice/resolve/main/audio_tokenizer/model.safetensors?download=true"
    Target = Join-Path $workspace "models\tts-omnivoice-0.6b\model\audio_tokenizer\model.safetensors"
  }
)

New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
$downloads = @()
foreach ($spec in $specs) {
  if ((Test-Path -LiteralPath $spec.Target) -and (Get-Item -LiteralPath $spec.Target).Length -eq $spec.Size) {
    continue
  }
  $partRoot = Join-Path $downloadRoot $spec.Name
  New-Item -ItemType Directory -Path $partRoot -Force | Out-Null
  $chunkSize = [int64][math]::Ceiling($spec.Size / $spec.Parts)
  for ($index = 0; $index -lt $spec.Parts; $index++) {
    $start = [int64]$index * $chunkSize
    $end = [int64][math]::Min($spec.Size - 1, $start + $chunkSize - 1)
    $fileName = "part-{0:D2}.bin" -f $index
    $path = Join-Path $partRoot $fileName
    $arguments = @(
      "-L", "--fail", "--silent", "--show-error",
      "--retry", "10", "--retry-delay", "2", "--retry-all-errors",
      "--range", "$start-$end", "--output", $fileName, $spec.Url
    )
    $process = Start-Process -FilePath "curl.exe" -ArgumentList $arguments `
      -WorkingDirectory $partRoot -WindowStyle Hidden -PassThru
    $downloads += [PSCustomObject]@{
      Process = $process
      Path = $path
      Expected = [int64]($end - $start + 1)
      Name = $spec.Name
      Index = $index
    }
  }
}

foreach ($download in $downloads) {
  $download.Process.WaitForExit()
  if ($download.Process.ExitCode -ne 0) {
    throw "Download failed: $($download.Name) part $($download.Index), curl $($download.Process.ExitCode)"
  }
  $actual = (Get-Item -LiteralPath $download.Path).Length
  if ($actual -ne $download.Expected) {
    throw "Size mismatch: $($download.Name) part $($download.Index): $actual / $($download.Expected)"
  }
}

foreach ($spec in $specs) {
  if ((Test-Path -LiteralPath $spec.Target) -and (Get-Item -LiteralPath $spec.Target).Length -eq $spec.Size) {
    continue
  }
  $partRoot = Join-Path $downloadRoot $spec.Name
  $assembled = $spec.Target + ".assembled-" + [guid]::NewGuid().ToString("N")
  $output = [IO.File]::Open($assembled, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
  try {
    foreach ($part in (Get-ChildItem -LiteralPath $partRoot -Filter "part-*.bin" | Sort-Object Name)) {
      $input = [IO.File]::OpenRead($part.FullName)
      try { $input.CopyTo($output) } finally { $input.Dispose() }
    }
  } finally {
    $output.Dispose()
  }
  if ((Get-Item -LiteralPath $assembled).Length -ne $spec.Size) {
    throw "Assembled size mismatch: $($spec.Name)"
  }
  [IO.File]::Move($assembled, $spec.Target)
}

foreach ($part in (Get-ChildItem -LiteralPath $downloadRoot -File -Recurse)) {
  [IO.File]::Delete($part.FullName)
}
foreach ($directory in (Get-ChildItem -LiteralPath $downloadRoot -Directory -Recurse | Sort-Object FullName -Descending)) {
  [IO.Directory]::Delete($directory.FullName)
}
[IO.Directory]::Delete($downloadRoot)

[PSCustomObject]@{
  status = "verified"
  main = (Get-Item -LiteralPath $specs[0].Target).Length
  codec = (Get-Item -LiteralPath $specs[1].Target).Length
} | ConvertTo-Json
