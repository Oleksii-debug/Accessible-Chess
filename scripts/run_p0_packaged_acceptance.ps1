param(
  [Parameter(Mandatory=$true)][string]$ProductRoot,
  [Parameter(Mandatory=$true)][string]$ProductSha,
  [string]$TopologyScript = '.v2-uia-evidence\stage1_uia_topology_v5.ps1',
  [string]$OutputDirectory = '.p0-packaged-acceptance',
  [int]$CopyTimeoutSeconds = 45,
  [int]$HotkeyTimeoutSeconds = 60,
  [string]$Python = 'python'
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Resolve-RepoPath([string]$Relative) {
  $repo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
  return (Resolve-Path -LiteralPath (Join-Path $repo $Relative)).Path
}

function Assert-ExactSha([string]$Value) {
  if($Value -notmatch '^[0-9A-Fa-f]{40}$'){
    throw 'ProductSha must be one exact 40-hex integration commit'
  }
}

function Invoke-PythonVerifier(
  [string]$Verifier,
  [string]$Evidence,
  [string]$Root,
  [string]$Sha
) {
  & $Python $Verifier --evidence $Evidence --product-root $Root --product-sha $Sha
  if($LASTEXITCODE -ne 0){
    throw "Evidence verifier failed: $Verifier"
  }
}

Assert-ExactSha $ProductSha
$product=(Resolve-Path -LiteralPath $ProductRoot).Path
$topology=(Resolve-Path -LiteralPath $TopologyScript).Path
$copyProbe=Resolve-RepoPath 'scripts/p0_packaged_document_copy_probe.ps1'
$hotkeyProbe=Resolve-RepoPath 'scripts/p0g_packaged_hotkey_result_probe.ps1'
$copyVerifier=Resolve-RepoPath 'scripts/verify_p0_packaged_document_copy_evidence.py'
$hotkeyVerifier=Resolve-RepoPath 'scripts/verify_p0g_packaged_hotkey_result_evidence.py'

$output=[System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $output -Force | Out-Null
$copyEvidence=Join-Path $output 'packaged-v2-document-copy-summary.json'
$hotkeyEvidence=Join-Path $output 'packaged-p0g-hotkey-result-summary.json'
Remove-Item -LiteralPath $copyEvidence,$hotkeyEvidence -Force -ErrorAction SilentlyContinue

Write-Host 'P0_PACKAGED_ACCEPTANCE_PHASE=COPY_PROBE'
& $copyProbe `
  -ProductRoot $product `
  -ProductSha $ProductSha `
  -TopologyScript $topology `
  -OutputPath $copyEvidence `
  -TimeoutSeconds $CopyTimeoutSeconds
if(-not (Test-Path -LiteralPath $copyEvidence -PathType Leaf)){
  throw 'Packaged semantic document-copy evidence was not produced'
}

Write-Host 'P0_PACKAGED_ACCEPTANCE_PHASE=COPY_VERIFY'
Invoke-PythonVerifier $copyVerifier $copyEvidence $product $ProductSha

Write-Host 'P0_PACKAGED_ACCEPTANCE_PHASE=HOTKEY_PROBE'
& $hotkeyProbe `
  -ProductRoot $product `
  -ProductSha $ProductSha `
  -TopologyScript $topology `
  -OutputPath $hotkeyEvidence `
  -TimeoutSeconds $HotkeyTimeoutSeconds
if(-not (Test-Path -LiteralPath $hotkeyEvidence -PathType Leaf)){
  throw 'Packaged P0-G hotkey-result evidence was not produced'
}

Write-Host 'P0_PACKAGED_ACCEPTANCE_PHASE=HOTKEY_VERIFY'
Invoke-PythonVerifier $hotkeyVerifier $hotkeyEvidence $product $ProductSha

$copy=(Get-Content -LiteralPath $copyEvidence -Raw -Encoding UTF8 | ConvertFrom-Json)
$hotkey=(Get-Content -LiteralPath $hotkeyEvidence -Raw -Encoding UTF8 | ConvertFrom-Json)
if(([string]$hotkey.product_sha).ToLowerInvariant() -cne $ProductSha.ToLowerInvariant()){
  throw 'P0-G evidence SHA changed after verifier completion'
}
if($copy.human_tested -eq $true -or $copy.nvda_verified -eq $true -or $hotkey.human_tested -eq $true -or $hotkey.nvda_verified -eq $true){
  throw 'Machine P0 acceptance evidence must never claim HUMAN_TESTED/NVDA_VERIFIED'
}

Write-Host 'P0 PACKAGED ACCEPTANCE VERIFIED: COPY + HOTKEY RESULTS'
