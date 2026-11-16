param([string]$SourceDirectory=$PSScriptRoot,[switch]$Uninstall,[switch]$Prepare,[string]$StatusFile,[long]$BootstrapWindow=0)
$ErrorActionPreference='Stop'
if($Prepare){
    try {
        function Preparation([string]$Text){[IO.File]::WriteAllText($StatusFile,$Text,(New-Object Text.UTF8Encoding($false)))}
        Preparation 'Microsoft Edge WebView2 prüfen …'
        $found=@('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients','HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients','HKCU:\Software\Microsoft\EdgeUpdate\Clients')|ForEach-Object{
            Get-ChildItem $_ -ErrorAction SilentlyContinue|ForEach-Object{Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue}|Where-Object{$_.name -like '*WebView2*' -and $_.pv -and $_.pv -ne '0.0.0.0'}
        }
        if(!$found){
            Preparation 'WebView2 fehlt. Microsoft-Laufzeit wird heruntergeladen …'
            $offline=Join-Path $PSScriptRoot 'client/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
            if(!(Test-Path -LiteralPath $offline)){
                [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -UseBasicParsing -OutFile $offline
            }
            Preparation 'Microsoft-Signatur prüfen und WebView2 einrichten …'
            $signature=Get-AuthenticodeSignature $offline
            if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation'){throw 'Die Microsoft-Signatur der WebView2-Laufzeit ist ungültig.'}
            $p=Start-Process $offline -ArgumentList '/silent /install' -Wait -PassThru
            if($p.ExitCode -notin @(0,3010)){throw "WebView2-Installation fehlgeschlagen (Exitcode $($p.ExitCode))."}
        }
        Preparation 'Installationsassistent öffnen …'
        exit 0
    }catch{Preparation ('Fehler: '+$_.Exception.Message);exit 1}
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class KienzledokuBootstrap { [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command); }'
$script:SetupScript=$PSCommandPath
if($Uninstall){& (Join-Path $PSScriptRoot 'UninstallUI.ps1');exit 0}
$form=New-Object Windows.Forms.Form
$form.Text='kienzledoku installieren 1.8.1';$form.ClientSize=New-Object Drawing.Size(750,300)
$form.StartPosition='CenterScreen';$form.BackColor=[Drawing.Color]::White;$form.AutoScaleMode='Dpi'
$form.Font=New-Object Drawing.Font('Segoe UI',11)
$title=New-Object Windows.Forms.Label;$title.Text='kienzledoku wird vorbereitet';$title.Font=New-Object Drawing.Font('Segoe UI',20);$title.SetBounds(32,32,680,50);$form.Controls.Add($title)
$label=New-Object Windows.Forms.Label;$label.Text='Voraussetzungen werden geprüft …';$label.SetBounds(32,104,680,65);$form.Controls.Add($label)
$bar=New-Object Windows.Forms.ProgressBar;$bar.Style='Marquee';$bar.SetBounds(32,185,680,16);$form.Controls.Add($bar)
$hint=New-Object Windows.Forms.Label;$hint.Text='Anschließend wählen Sie Komponenten, Verbindungen, Modelle und Dokumentation.';$hint.SetBounds(32,224,680,52);$form.Controls.Add($hint)
$close=New-Object Windows.Forms.Button;$close.Text='Schließen';$close.SetBounds(562,225,150,38);$close.Visible=$false;$close.Add_Click({$form.Close()});$form.Controls.Add($close)
$script:child=$null;$script:phase='initial';$script:failed=$false;$script:allowClose=$false
$taskDir=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-start-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($taskDir)|Out-Null
$statusPath=Join-Path $taskDir 'status.txt';$readyPath=Join-Path $taskDir 'ready.txt'
function Start-Child([string]$Exe,[string]$Arguments){
    $info=New-Object Diagnostics.ProcessStartInfo;$info.FileName=$Exe;$info.Arguments=$Arguments
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true
    return [Diagnostics.Process]::Start($info)
}
$form.Add_FormClosing({param($sender,$e)if(!$script:allowClose -and !$script:failed){$e.Cancel=$true}})
$timer=New-Object Windows.Forms.Timer;$timer.Interval=150
$timer.Add_Tick({
    try{
        if($script:phase -eq 'initial'){
            $script:child=Start-Child (Join-Path $env:windir 'System32/WindowsPowerShell/v1.0/powershell.exe') ('-NoProfile -ExecutionPolicy Bypass -File "'+$script:SetupScript+'" -Prepare -StatusFile "'+$statusPath+'"')
            $script:phase='prepare';return
        }
        if(Test-Path -LiteralPath $statusPath){$label.Text=[IO.File]::ReadAllText($statusPath)}
        if($script:phase -eq 'prepare' -and $script:child.HasExited){
            $script:child.WaitForExit();if($script:child.ExitCode -ne 0){throw $label.Text};$script:child.Dispose()
            $script:child=Start-Child (Join-Path $PSScriptRoot 'client/runtime/pythonw.exe') ('-m installer.windows_launch --ready-file "'+$readyPath+'"')
            $script:phase='wizard'
        }
        if($script:phase -eq 'wizard'){
            if(Test-Path -LiteralPath $readyPath){
                $ready=[IO.File]::ReadAllText($readyPath)
                if($ready -ne 'ready'){throw $ready}
                $timer.Stop();$script:allowClose=$true;$form.Close()
            }elseif($script:child.HasExited){throw 'Der Installationsassistent konnte nicht gestartet werden. Bitte die Voraussetzungen und das Paket prüfen.'}
        }
    }catch{$script:failed=$true;$timer.Stop();$bar.Style='Blocks';$label.Text=$_.Exception.Message;$hint.Visible=$false;$close.Visible=$true}
})
$form.Add_Shown({if($BootstrapWindow){[KienzledokuBootstrap]::ShowWindow([IntPtr]$BootstrapWindow,0)|Out-Null};$timer.Start()})
try{
    $null=$form.ShowDialog()
    # Keep the extracted package alive until the wizard and its operations finish.
    if(!$script:failed -and $script:child){$script:child.WaitForExit();exit $script:child.ExitCode}
    exit 1
}finally{$timer.Dispose();$form.Dispose();if($script:child){$script:child.Dispose()};Remove-Item -LiteralPath $taskDir -Recurse -Force -ErrorAction SilentlyContinue}
