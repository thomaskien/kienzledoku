$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
. (Join-Path $root 'windows/Update.ps1')
$base=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-update-test-'+[guid]::NewGuid().ToString('N'))
$source=Join-Path $base 'source';$target=Join-Path $base 'installed';$config=Join-Path $base 'config.toml'
function Assert($test,$message){if(!$test){throw $message}}
try {
 $null=[IO.Directory]::CreateDirectory($source);$null=[IO.Directory]::CreateDirectory($target)
 Set-Content (Join-Path $source 'kienzledoku.py') '# new'
 Set-Content (Join-Path $target 'kienzledoku.py') '# old'
 Set-Content (Join-Path $target 'obsolete.py') '# stale'
 Set-Content $config '# preserved'
 $t=Start-CodeUpdate $source $target 'kienzledoku.py'
 Assert (!(Test-Path (Join-Path $target 'obsolete.py'))) 'Overlay left obsolete code'
 Assert (Test-Path (Join-Path $t.Work 'previous/obsolete.py')) 'No pre-validation backup'
 Complete-CodeUpdate $t
 Assert (!(Test-Path $t.Work)) 'Backup survived successful completion'
 Assert ((Get-Content $config) -eq '# preserved') 'Configuration changed'
 $t=Start-CodeUpdate $source $target 'kienzledoku.py'
 Set-Content (Join-Path $target 'unexpected.py') '# stale'
 $blocked=$false;try{Complete-CodeUpdate $t}catch{$blocked=$true}
 Assert $blocked 'False success on extra active code'
 Undo-CodeUpdate $t
 Assert (!(Test-Path (Join-Path $target 'unexpected.py'))) 'Rollback failed'
 # Promotion and rollback can both fail, e.g. if another process holds a file.
 # The previous tree must survive even that double failure.
 function Move-Item {
  param([string]$LiteralPath,[string]$Destination)
  if([IO.Path]::GetFileName($LiteralPath) -in @('candidate','previous')){throw 'synthetic move failure'}
  Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination
 }
 $blocked=$false;try{Start-CodeUpdate $source $target 'kienzledoku.py'}catch{$blocked=$true}
 Remove-Item Function:\Move-Item
 Assert $blocked 'Synthetic move failures did not propagate'
 $saved=@(Get-ChildItem -LiteralPath $base -Directory -Force -Filter '.kienzledoku-update-*')
 Assert ($saved.Count -eq 1) 'Failed rollback discarded transaction'
 Assert ((Get-Content (Join-Path $saved[0].FullName 'previous/kienzledoku.py')) -eq '# new') 'Failed rollback discarded previous code'
 Move-Item -LiteralPath (Join-Path $saved[0].FullName 'previous') -Destination $target
 Remove-Item -LiteralPath $saved[0].FullName -Recurse -Force
 $script:processes=@([pscustomobject]@{ProcessId=123;ExecutablePath=(Join-Path $target 'runtime/pythonw.exe');CommandLine=''})
 function Get-CimInstance {return $script:processes}
 $blocked=$false;try{Assert-ClientClosed $target}catch{$blocked=$true}
 Assert $blocked 'Active client not blocked'
 $script:processes=@();Assert-ClientClosed $target
 foreach($relative in @('windows/Update.ps1','windows/install.ps1','server-windows/windows/Engine.ps1')){
  $errors=$null;$tokens=$null
  $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root $relative),[ref]$tokens,[ref]$errors)
  Assert (!$errors.Count) ('Parse failed: '+$relative)
 }
 Assert ((Get-FileHash (Join-Path $root 'windows/Update.ps1')).Hash -eq (Get-FileHash (Join-Path $root 'server-windows/windows/Update.ps1')).Hash) 'Update helper copies differ'
 Write-Output 'PASS: fresh payload, obsolete-file cleanup, config retention, rollback, double-failure recovery, incomplete cleanup rejection, active-client guard; portable test only.'
} finally {if(Test-Path $base){Remove-Item -LiteralPath $base -Recurse -Force}}
