param([string]$WizardPath='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
if(-not $WizardPath){$WizardPath=Join-Path $root 'windows/Wizard.ps1'}
$source=[IO.File]::ReadAllText($WizardPath).Replace("`r`n","`n")
$start=$source.LastIndexOf("`nUpdate-DefaultModels`n")
$end=$source.IndexOf('$null=$script:Form.ShowDialog()',$start)
if($start -lt 0 -or $end -lt 0){throw 'Startup migration not found.'}
$migration=[scriptblock]::Create($source.Substring($start,$end-$start))
function Update-DefaultModels {}
function Update-ParallelModels([string]$Preferred){$script:RestoredParallel=$Preferred}
function Update-Reserve {}
function Refresh-Inventory {}
function Show-Page([int]$Index){}
$scenarios=@(
    @{Name='Legacy 1.4 auto with a resident Q4';Version='1.4';Mode='auto';Default='9b-q4';Expected='9b-q4';Explicit=$false;Parallel=''},
    @{Name='Legacy 1.5 auto with a serial 27B default';Version='1.5';Mode='auto';Default='27b-q4';Expected='';Explicit=$false;Parallel=''},
    @{Name='Legacy serial configuration';Version='1.5';Mode='serial';Default='9b-q4';Expected='';Explicit=$false;Parallel=''},
    @{Name='Explicit Q6 resident and independent Q4 default';Version='1.6';Mode='selected';Default='9b-q4';Expected='9b-q6';Explicit=$true;Parallel='9b-q6'},
    @{Name='Explicit all-serial selection';Version='1.6';Mode='selected';Default='9b-q4';Expected='';Explicit=$true;Parallel=''},
    @{Name='Fresh installation without previous settings';Version='';Mode='';Default='9b-q4';Expected='9b-q4';Explicit=$false;Parallel='';Fresh=$true}
)
$passed=0
# Execute at the script's top level, just like Wizard.ps1. Wrapping this in a
# function would hide case-insensitive collisions with script-level controls.
foreach($scenario in $scenarios){
    $script:Default=[pscustomobject]@{SelectedItem='9b-q4'}
    $originalDefaultControl=$script:Default
    $script:Ram=[pscustomobject]@{SelectedIndex=0}
    $script:DiskCache=[pscustomobject]@{Checked=$false}
    $script:Autostart=[pscustomobject]@{Checked=$false}
    $script:StartAfter=[pscustomobject]@{Checked=$false}
    $script:Verify=[pscustomobject]@{Checked=$true}
    $script:Lan=[pscustomobject]@{Checked=$false}
    $script:Address=[pscustomobject]@{Items=@('10.0.83.140 — Ethernet');SelectedItem=$null}
    $script:RestoredParallel='unset'
    $script:Previous=[pscustomobject]@{Version=$scenario.Version;Mode=$scenario.Mode;DefaultModel=$scenario.Default;
        WslRamGiB=32;AudioCache='ram';Autostart=$true;StartAfterInstall=$true;Verify=$true;NetworkMode='lan';NetworkAddress='10.0.83.140';
        Profiles=[pscustomobject]@{'9b-q4'=[pscustomobject]@{Mode='parallel'};'27b-q4'=[pscustomobject]@{Mode='serial'}}}
    if($scenario.Explicit){$script:Previous | Add-Member -NotePropertyName ParallelModel -NotePropertyValue $scenario.Parallel}
    if($scenario.ContainsKey('Fresh')){$script:Previous=$null}
    . $migration
    # This is the exact property access performed by Build-Config on Weiter.
    $requestDefault=$script:Default.SelectedItem
    if(-not [object]::ReferenceEquals($originalDefaultControl,$script:Default)){throw 'Standardmodell-Steuerelement wurde überschrieben.'}
    if($requestDefault -ne $scenario.Default -or $script:RestoredParallel -ne $scenario.Expected){throw ('Falsche Übernahme: '+$scenario.Name)}
    if($script:Previous -and (-not $script:Lan.Checked -or $script:Address.SelectedItem -ne '10.0.83.140 — Ethernet')){throw 'LAN-Auswahl wurde nicht erhalten.'}
    $passed++;Write-Output ('PASS '+$scenario.Name)
}
Write-Output "All $passed wizard startup migration cases passed (actual startup statements; simulated controls; no Windows GUI executed)."
