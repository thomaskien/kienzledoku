# Shared setup/uninstall functions; dot-source without changing the system.
function Assert-KienzledokuPath([string]$Path) {
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    while($item){
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Verknüpfte Installationspfade werden nicht automatisch entfernt.'}
        $item=$item.Parent
    }
}
function Assert-KienzledokuTree([string]$Path) {
    Assert-KienzledokuPath $Path
    if(Test-Path -LiteralPath $Path){
        foreach($item in @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)){
            if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Verknüpfte Inhalte werden nicht automatisch entfernt.'}
        }
    }
}
function Assert-KienzledokuClosed([string]$ClientDirectory) {
    $prefix=[IO.Path]::GetFullPath($ClientDirectory).TrimEnd('\')+'\'
    # Do not stop any process. A failed process inventory must abort safely.
    $processes=@(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach($process in $processes){
        if($process.ExecutablePath -and $process.ExecutablePath.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){
            throw 'Bitte zuerst alle Kienzledoku-Aufnahme- und Einstellungsfenster schließen. Es wird keine Aufnahme verworfen.'
        }
    }
}
function Get-KienzledokuComponents {
    $client=Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku record'
    $reg=Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\kienzledoku-server' -ErrorAction SilentlyContinue
    $serverConfig=$null
    if($reg -and $reg.InstallLocation){
        $candidate=Join-Path $reg.InstallLocation 'config.json'
        if(Test-Path -LiteralPath $candidate){$serverConfig=$candidate}
    }
    $saved=Join-Path $env:LOCALAPPDATA 'kienzledoku-installer/server-location.json'
    if(!(Test-Path -LiteralPath $saved)){$saved=Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku Setup/server-location.json'}
    if(-not $serverConfig -and (Test-Path -LiteralPath $saved)){
        $candidate=(Get-Content -LiteralPath $saved -Raw|ConvertFrom-Json).config
        if($candidate -and (Test-Path -LiteralPath $candidate)){$serverConfig=$candidate}
    }
    return @{Client=$client;ClientInstalled=(Test-Path -LiteralPath (Join-Path $client 'kienzledoku.py'));ServerConfig=$serverConfig}
}
function Remove-KienzledokuClient([string]$Destination,[switch]$RemoveSettings) {
    $expected=Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku record'
    if([IO.Path]::GetFullPath($Destination).TrimEnd('\') -ne [IO.Path]::GetFullPath($expected).TrimEnd('\')){throw 'Unbekannter Client-Installationspfad.'}
    $data=Join-Path $env:LOCALAPPDATA 'kienzledoku record'
    Assert-KienzledokuTree $Destination
    if($RemoveSettings){Assert-KienzledokuTree $data}
    Assert-KienzledokuClosed $Destination
    foreach($scheme in @('kienzledoku','kienzledoku-record')){
        $key="HKCU:\Software\Classes\$scheme"
        $command=(Get-ItemProperty "$key\shell\open\command" -ErrorAction SilentlyContinue).'(default)'
        $connect='"'+(Join-Path $Destination 'kienzleconnect.exe')+'" "%1"'
        $direct='"'+(Join-Path $Destination 'runtime/pythonw.exe')+'" "'+(Join-Path $Destination 'kienzledoku_launch.py')+'" "%1"'
        if($command -ceq $connect -or $command -ceq $direct){Remove-Item -LiteralPath $key -Recurse -Force}
    }
    $link=Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku record.lnk'
    if(Test-Path -LiteralPath $link){
        $shell=New-Object -ComObject WScript.Shell
        if($shell.CreateShortcut($link).TargetPath -eq (Join-Path $Destination 'runtime/pythonw.exe')){Remove-Item -LiteralPath $link -Force}
    }
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    if($RemoveSettings -and (Test-Path -LiteralPath $data)){Remove-Item -LiteralPath $data -Recurse -Force}
}
function Show-KienzledokuUninstall {
    $installed=Get-KienzledokuComponents
    $form=New-Page 'kienzledoku deinstallieren' 450
    $null=New-Label $form 'Komponenten auswählen. Offene Aufnahmen zuerst schließen.' 25 20 670 45
    $client=New-Object Windows.Forms.CheckBox;$client.Text='Client (Record und Connect)';$client.SetBounds(30,80,650,35);$client.Enabled=$installed.ClientInstalled;$client.Checked=$client.Enabled;$form.Controls.Add($client)
    $server=New-Object Windows.Forms.CheckBox;$server.Text='Server (Commander und KI-Dienste)';$server.SetBounds(30,125,650,35);$server.Enabled=[bool]$installed.ServerConfig;$server.Checked=$server.Enabled;$form.Controls.Add($server)
    $models=New-Object Windows.Forms.CheckBox;$models.Text='Servermodelle und eigene Kienzledoku-WSL-Umgebung entfernen';$models.SetBounds(30,180,660,40);$models.Enabled=$server.Enabled;$form.Controls.Add($models)
    $settings=New-Object Windows.Forms.CheckBox;$settings.Text='Technische Einstellungen und gespeicherte Zugangstokens entfernen';$settings.SetBounds(30,230,660,40);$form.Controls.Add($settings)
    $null=New-Label $form 'Ohne Modellentfernung bleibt die deaktivierte WSL-Umgebung erhalten. Downloadarchive und andere WSL-Umgebungen bleiben erhalten. Auch Aufnahmen auf verbundenen Rechnern vorher beenden.' 30 285 660 75
    $go=New-Button $form 'Deinstallieren' 490 385 200;$go.DialogResult='OK'
    $cancel=New-Button $form 'Abbrechen' 275 385 200;$cancel.DialogResult='Cancel'
    try {
        if($form.ShowDialog() -ne 'OK'){return}
        if(-not $client.Checked -and -not $server.Checked){return}
        Assert-KienzledokuClosed $installed.Client
        if($client.Checked){
            Assert-KienzledokuTree $installed.Client
            if($settings.Checked){Assert-KienzledokuTree (Join-Path $env:LOCALAPPDATA 'kienzledoku record')}
        }
        if($server.Checked){
            Assert-KienzledokuPath $installed.ServerConfig
            $cfg=Get-Content -LiteralPath $installed.ServerConfig -Raw|ConvertFrom-Json
            if([IO.Path]::GetFullPath($installed.ServerConfig) -ne [IO.Path]::GetFullPath((Join-Path $cfg.InstallDirectory 'config.json'))){throw 'Serverkonfiguration stimmt nicht mit dem Installationspfad überein.'}
            Assert-KienzledokuPath $cfg.InstallDirectory
            if([IO.Path]::GetFullPath($cfg.StateDirectory) -ne [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'kienzledoku-server'))){throw 'Unbekanntes Server-Einstellungsverzeichnis; keine Dateien werden entfernt.'}
            Assert-KienzledokuPath $cfg.StateDirectory
            $parameters=@{Action='Uninstall';ConfigPath=$installed.ServerConfig;RemoveModels=$models.Checked;RemoveSettings=$settings.Checked}
            $engine=Join-Path $PSScriptRoot 'server/windows/Engine.ps1'
            & $engine @parameters
            if($LASTEXITCODE -ne 0){throw 'Server-Deinstallation nicht abgeschlossen. Client unverändert.'}
        }
        if($client.Checked){Remove-KienzledokuClient $installed.Client -RemoveSettings:$settings.Checked}
        [Windows.Forms.MessageBox]::Show('Die gewählten Komponenten wurden entfernt bzw. der Server bei behaltenen Modellen deaktiviert.','kienzledoku','OK','Information')|Out-Null
        Complete-KienzledokuUninstall $installed $server.Checked $models.Checked
    } finally {$form.Dispose()}
}
function Install-KienzledokuMaintenance {
    $destination=Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku Setup'
    . (Join-Path $PSScriptRoot 'Update.ps1')
    $installed=Get-KienzledokuComponents
    $transaction=$null
    if([IO.Path]::GetFullPath($PSScriptRoot) -ne [IO.Path]::GetFullPath($destination)){
        $names=@('Setup.ps1','SetupUninstall.ps1','UninstallUI.ps1','Update.ps1','server','docs','release.json')|Where-Object {Test-Path -LiteralPath (Join-Path $PSScriptRoot $_)}
        $transaction=Start-CodeUpdate $PSScriptRoot $destination 'SetupUninstall.ps1' $names
    }
    if($installed.ServerConfig){
        $state=Join-Path $env:LOCALAPPDATA 'kienzledoku-installer'
        $null=[IO.Directory]::CreateDirectory($state)
        @{config=$installed.ServerConfig}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $state 'server-location.json') -Encoding UTF8
    }
    $ps=Join-Path $env:windir 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $args='-NoProfile -ExecutionPolicy Bypass -STA -File "'+(Join-Path $destination 'Setup.ps1')+'" -Uninstall'
    $reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\kienzledoku'
    New-Item -Force $reg|Out-Null
    foreach($entry in @(@('DisplayName','kienzledoku'),@('DisplayVersion','1.8.3'),@('Publisher','Dr. Thomas Kienzle'),@('UninstallString','"'+$ps+'" '+$args))){Set-ItemProperty $reg -Name $entry[0] -Value $entry[1]}
    $shell=New-Object -ComObject WScript.Shell
    $shortcut=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku deinstallieren.lnk'))
    $shortcut.TargetPath=$ps;$shortcut.Arguments=$args;$shortcut.Save()
    Complete-CodeUpdate $transaction
}

function Complete-KienzledokuUninstall($installed,[bool]$RemovedServer,[bool]$RemovedModels) {
        if(-not (Test-Path -LiteralPath $installed.Client) -and (-not $installed.ServerConfig -or ($RemovedServer -and $RemovedModels))){
            $maintenance=Join-Path $env:LOCALAPPDATA 'Programs/kienzledoku Setup'
            Assert-KienzledokuTree $maintenance
            $reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\kienzledoku'
            $entry=Get-ItemProperty -LiteralPath $reg -ErrorAction SilentlyContinue
            if($entry -and $entry.UninstallString -and $entry.UninstallString.Contains('"'+(Join-Path $maintenance 'Setup.ps1')+'"')){Remove-Item -LiteralPath $reg -Recurse -Force}
            $link=Join-Path ([Environment]::GetFolderPath('Programs')) 'kienzledoku deinstallieren.lnk'
            if(Test-Path -LiteralPath $link){
                $shell=New-Object -ComObject WScript.Shell
                if($shell.CreateShortcut($link).Arguments.Contains('"'+(Join-Path $maintenance 'Setup.ps1')+'"')){Remove-Item -LiteralPath $link -Force}
            }
            if(Test-Path -LiteralPath $maintenance){Remove-Item -LiteralPath $maintenance -Recurse -Force}
        }
}
