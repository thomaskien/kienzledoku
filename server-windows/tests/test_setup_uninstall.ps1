$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$errors=$null;$tokens=$null
foreach($file in @('windows/Setup.ps1','windows/SetupUninstall.ps1','windows/uninstall.ps1','server-windows/windows/Engine.ps1')){
 $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root $file),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ($errors|Out-String)}
}
. (Join-Path $root 'windows/SetupUninstall.ps1')
# Mock only process inventory, exercise actual guard. Never touch Windows state.
$script:inventory=@([pscustomobject]@{ExecutablePath='C:\Other\python.exe'})
function Get-CimInstance {return $script:inventory}
# GetFullPath is platform-specific, construct exactly the guard's canonical prefix.
$base=Join-Path ([IO.Path]::GetTempPath()) 'synthetic-kienzledoku-client'
Assert-KienzledokuClosed $base
$script:inventory=@([pscustomobject]@{ExecutablePath=([IO.Path]::GetFullPath($base).TrimEnd('\')+'\runtime\pythonw.exe')})
$blocked=$false;try{Assert-KienzledokuClosed $base}catch{$blocked=$_.Exception.Message -match 'zuerst alle'}
if(-not $blocked){throw 'Eigener laufender Client wurde nicht blockiert.'}
function Get-CimInstance {throw 'synthetic inventory failure'}
$blocked=$false;try{Assert-KienzledokuClosed $base}catch{$blocked=$true}
if(-not $blocked){throw 'Unbekannter Prozesszustand darf nicht freigegeben werden.'}
Write-Output 'PASS: Parser, fremde Prozesse, eigene offene Fenster, fehlgeschlagene Inventur; keine native Windows-Deinstallation ausgeführt.'

# Execute the real engine uninstall branch with all system effects intercepted.
# Keeping models must never unregister a distro; removal is restricted to ours.
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'server-windows/windows/Engine.ps1'),[ref]$tokens,[ref]$errors)
$body=$null
foreach($statement in $ast.FindAll({param($node) $node -is [Management.Automation.Language.IfStatementAst]},$true)){
 foreach($clause in $statement.Clauses){
  if($clause.Item1.Extent.Text -eq '$Action -eq ''Uninstall'''){$body=$clause.Item2.Extent.Text}
 }
}
if(-not $body){throw 'Engine uninstall branch missing'}
$uninstall=[scriptblock]::Create($body.Substring(1,$body.Length-2))
function Wsl {param([object[]]$Arguments) $script:wslCalls+=,@($Arguments)}
function Invoke-WslManagement {param([object[]]$Arguments) $script:managementCalls+=,@($Arguments)}
function Write-Json {}
function Configure-Network {}
function Remove-ItemProperty {}
function Remove-Item {}
function Log {}
function Join-Path {param([string]$Path,[string]$ChildPath) [IO.Path]::Combine($Path,$ChildPath)}
$script:Cfg=[pscustomobject]@{InstallDirectory='synthetic-install';StateDirectory='synthetic-state'}
$ConfigPath='synthetic-config';$RemoveSettings=$false
foreach($RemoveModels in @($false,$true)){
 $script:managementCalls=@();$script:wslCalls=@()
 & $uninstall
 $unregister=@($script:managementCalls|Where-Object {$_[0] -eq '--unregister'})
 if($unregister.Count -ne [int]$RemoveModels){throw 'Wrong WSL removal decision'}
 foreach($call in $script:managementCalls){
  if($call.Count -ne 2 -or $call[1] -ne 'kienzledoku-server' -or $call[0] -notin @('--terminate','--unregister')){throw 'Uninstall touched a foreign distro or global WSL state'}
 }
 $expected=if($RemoveModels){'remove-models'}else{'stop'}
 if($script:wslCalls.Count -ne 1 -or $script:wslCalls[0][-1] -ne $expected){throw 'Wrong Linux uninstall operation'}
}
Write-Output 'PASS: actual uninstall branch with intercepted effects; keep/remove models, only own WSL distro, no global WSL removal.'
