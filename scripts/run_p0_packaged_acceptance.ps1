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

function Assert-NoMachineHumanClaim($Evidence,[string]$Label) {
  foreach($name in @('human_tested','nvda_verified')){
    $property=$Evidence.PSObject.Properties[$name]
    if($null -eq $property -or $property.Value -isnot [bool] -or $property.Value -ne $false){
      throw "$Label machine evidence must explicitly declare $name=false"
    }
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

# The copy verifier above independently binds ProductSha to RELEASE_MANIFEST.json,
# SHA256SUMS.txt and the exact direct packaged executable before we execute that
# executable for the P0-F reachability diagnostic.  This keeps the orchestrator
# on the incumbent package-identity authority instead of inventing a second one.
$exe=Join-Path $product 'AccessibleChess.exe'
$starterRoot=Join-Path $product 'release-content\w2-starter'
if(-not (Test-Path -LiteralPath $exe -PathType Leaf)){
  throw 'Packaged AccessibleChess.exe is missing before P0-F diagnostic'
}
if(-not (Test-Path -LiteralPath $starterRoot -PathType Container)){
  throw 'Packaged P0-F W2 starter root is missing'
}

Write-Host 'P0_PACKAGED_ACCEPTANCE_PHASE=STARTER_DIAGNOSTIC'
$diagnosticLines=@(& $exe --diagnostic 2>&1)
$diagnosticExit=$LASTEXITCODE
if($diagnosticExit -ne 0){
  throw "Packaged P0-F diagnostic failed with exit code $diagnosticExit"
}
$starterPass=$false
foreach($line in $diagnosticLines){
  if(([string]$line).Trim() -ceq 'P0-F PACKAGED W2 LIBRARY DIAGNOSTIC PASS'){
    $starterPass=$true
  }
}
if(-not $starterPass){
  throw 'Packaged P0-F diagnostic did not prove W2 Library reachability'
}
Write-Host 'P0_PACKAGED_STARTER_REACHABILITY=VERIFIED'

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

# All packaged executable phases have now completed. Re-run both independent
# verifiers so a later diagnostic/probe cannot alter earlier evidence after its
# first verification and still reach the aggregate PASS marker.
Write-Host 'P0_PACKAGED_ACCEPTANCE_PHASE=FINAL_REVERIFY'
Invoke-PythonVerifier $copyVerifier $copyEvidence $product $ProductSha
Invoke-PythonVerifier $hotkeyVerifier $hotkeyEvidence $product $ProductSha

$copy=(Get-Content -LiteralPath $copyEvidence -Raw -Encoding UTF8 | ConvertFrom-Json)
$hotkey=(Get-Content -LiteralPath $hotkeyEvidence -Raw -Encoding UTF8 | ConvertFrom-Json)
if(([string]$copy.product_sha).ToLowerInvariant() -cne $ProductSha.ToLowerInvariant()){
  throw 'Document-copy evidence SHA changed after final verifier completion'
}
if(([string]$hotkey.product_sha).ToLowerInvariant() -cne $ProductSha.ToLowerInvariant()){
  throw 'P0-G evidence SHA changed after final verifier completion'
}
Assert-NoMachineHumanClaim $copy 'document-copy'
Assert-NoMachineHumanClaim $hotkey 'P0-G hotkey-result'

Write-Host 'P0 PACKAGED ACCEPTANCE VERIFIED: COPY + STARTER + HOTKEY RESULTS'
