param([string]$SourceDirectory='', [string]$ResumeConfig='')
Set-StrictMode -Version 2
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
trap {
    [Windows.Forms.MessageBox]::Show($_.Exception.Message,'kienzledoku Server Installer — Fehler','OK','Error')|Out-Null
    exit 1
}
Import-Module (Join-Path $PSScriptRoot 'Core.psm1') -Force
$script:InstallerVersion=Get-InstallerVersion
[Windows.Forms.Application]::EnableVisualStyles()
$script:WizardMutex=New-Object Threading.Mutex($false,'Local\kienzledoku-server-installer')
if(-not $script:WizardMutex.WaitOne(0)){
    [Windows.Forms.MessageBox]::Show('Der Installationsassistent ist bereits geöffnet.','kienzledoku Server Installer')|Out-Null
    exit 0
}
$script:Root=Split-Path -Parent $PSScriptRoot
if(-not $SourceDirectory){$SourceDirectory=$script:Root}
$script:Catalog=Get-Catalog $script:Root
$script:State=Join-Path $env:LOCALAPPDATA 'kienzledoku-server'
$script:InstalledRoot=Join-Path $env:LOCALAPPDATA 'Programs\kienzledoku Server'
$script:Previous=$null
if($ResumeConfig -and (Test-Path -LiteralPath $ResumeConfig)){$script:Previous=Read-Json $ResumeConfig}
elseif(Test-Path -LiteralPath (Join-Path $script:InstalledRoot 'config.json')){$script:Previous=Read-Json (Join-Path $script:InstalledRoot 'config.json')}
$script:Hardware=$null;$hardwareMessage=''
try{$script:Hardware=Get-Hardware}catch{$hardwareMessage='Hardwareerkennung nicht verfügbar. Der reine Downloadmodus ist weiterhin nutzbar.'}
$script:Page=0;$script:Process=$null;$script:Busy=$false;$script:Cfg=$null
$script:CanCancelAdminRetry=$false;$script:AdminCancelSent=$false
$script:Form=New-Object Windows.Forms.Form
$script:Form.Text='kienzledoku Server Installer '+$script:InstallerVersion
$script:Form.ClientSize=New-Object Drawing.Size(920,748)
$script:Form.MinimumSize=New-Object Drawing.Size(936,787)
$script:Form.StartPosition='CenterScreen'
$script:Form.Font=New-Object Drawing.Font('Segoe UI',10)
$script:Form.BackColor=[Drawing.Color]::White
$script:Form.AutoScaleMode=[Windows.Forms.AutoScaleMode]::Dpi
$header=New-Object Windows.Forms.Panel;$header.Dock='Top';$header.Height=100;$header.BackColor=[Drawing.Color]::FromArgb(22,49,70)
$script:Form.Controls.Add($header)
function Label($Parent,[string]$Text,[int]$X,[int]$Y,[int]$Width,[int]$Height=28){
    $c=New-Object Windows.Forms.Label;$c.Text=$Text;$c.Location=New-Object Drawing.Point($X,$Y);$c.Size=New-Object Drawing.Size($Width,$Height);$Parent.Controls.Add($c);return $c
}
function TextBox($Parent,[string]$Text,[int]$X,[int]$Y,[int]$Width,[int]$Height=30,[bool]$Multiline=$false){
    $c=New-Object Windows.Forms.TextBox;$c.Text=$Text;$c.Location=New-Object Drawing.Point($X,$Y);$c.Size=New-Object Drawing.Size($Width,$Height);$c.Multiline=$Multiline;$Parent.Controls.Add($c);return $c
}
function Button($Parent,[string]$Text,[int]$X,[int]$Y,[int]$Width=120){
    $c=New-Object Windows.Forms.Button;$c.Text=$Text;$c.Location=New-Object Drawing.Point($X,$Y);$c.Size=New-Object Drawing.Size($Width,34);$Parent.Controls.Add($c);return $c
}
function Check($Parent,[string]$Text,[int]$Y,[bool]$Checked=$false){
    $c=New-Object Windows.Forms.CheckBox;$c.Text=$Text;$c.Checked=$Checked;$c.Location=New-Object Drawing.Point(24,$Y);$c.Size=New-Object Drawing.Size(820,30);$Parent.Controls.Add($c);return $c
}
function Radio($Parent,[string]$Text,[int]$Y,[bool]$Checked=$false){
    $c=New-Object Windows.Forms.RadioButton;$c.Text=$Text;$c.Checked=$Checked;$c.Location=New-Object Drawing.Point(24,$Y);$c.Size=New-Object Drawing.Size(820,32);$Parent.Controls.Add($c);return $c
}
function Combo($Parent,[int]$X,[int]$Y,[int]$Width){
    $c=New-Object Windows.Forms.ComboBox;$c.DropDownStyle='DropDownList';$c.Location=New-Object Drawing.Point($X,$Y);$c.Width=$Width;$Parent.Controls.Add($c);return $c
}
function Browse-Folder($Target){
    $dialog=New-Object Windows.Forms.FolderBrowserDialog;$dialog.Description='Verzeichnis wählen (SSD oder Netzlaufwerk). UNC-Pfade können auch direkt eingegeben werden.'
    if(Test-Path -LiteralPath $Target.Text){$dialog.SelectedPath=$Target.Text}
    if($dialog.ShowDialog() -eq 'OK'){$Target.Text=$dialog.SelectedPath}
    $dialog.Dispose()
}
$title=Label $header 'kienzledoku Server Installer' 24 18 850 38
$title.Font=New-Object Drawing.Font('Segoe UI',20,[Drawing.FontStyle]::Bold);$title.ForeColor=[Drawing.Color]::White
$subtitle=Label $header ('Version '+$script:InstallerVersion+'  ·  Windows 11 x64  ·  NVIDIA / WSL2  ·  Serverkomponenten') 26 64 850 24
$subtitle.ForeColor=[Drawing.Color]::FromArgb(205,224,235)
$footer=New-Object Windows.Forms.Panel;$footer.Dock='Bottom';$footer.Height=66;$footer.BackColor=[Drawing.Color]::FromArgb(242,245,247);$script:Form.Controls.Add($footer)
$script:Back=Button $footer 'Zurück' 496 16 120
$script:Next=Button $footer 'Weiter' 628 16 124
$script:Cancel=Button $footer 'Schließen' 764 16 132
$script:Step=Label $footer '' 24 20 450 32
$body=New-Object Windows.Forms.Panel;$body.Dock='Fill';$script:Form.Controls.Add($body);$body.BringToFront()
$script:Pages=@()
foreach($i in 0..6){$p=New-Object Windows.Forms.Panel;$p.Dock='Fill';$p.AutoScroll=$true;$p.Visible=$false;$body.Controls.Add($p);$script:Pages+=,$p}

# 1: first decision and startup inventory; scanning deliberately avoids full hashes.
$p=$script:Pages[0]
$null=Label $p 'Was möchten Sie durchführen?' 24 18 850 32
$script:InstallRadio=Radio $p 'Server installieren oder vorhandene Installation reparieren' 55 $true
$script:DownloadRadio=Radio $p 'Nur Modelle herunterladen / SSD oder Netzlaufwerk vorbereiten (ohne WSL)' 91
$null=Label $p 'Modellarchiv (Unterverzeichnis models; auch als Ziel auf einer tragbaren SSD möglich)' 24 137 850 26
$cacheDefault=Join-Path $SourceDirectory 'models'
if($script:Previous){$cacheDefault=$script:Previous.CacheDirectory}
$script:Cache=TextBox $p $cacheDefault 24 166 718
$browse=Button $p 'Wählen …' 754 164 130;$browse.Add_Click({Browse-Folder $script:Cache;Refresh-Inventory})
$null=Label $p 'Weitere Modellquellen (eine Zeile je Verzeichnis; lokale Ordner oder \\Server\Freigabe)' 24 210 850 26
$script:Sources=TextBox $p '' 24 240 718 55 $true
if($script:Previous){$script:Sources.Text=@($script:Previous.Sources) -join "`r`n"}
$add=Button $p 'Hinzufügen …' 754 240 130
$add.Add_Click({$d=New-Object Windows.Forms.FolderBrowserDialog;if($d.ShowDialog() -eq 'OK'){$script:Sources.AppendText($d.SelectedPath+"`r`n")};$d.Dispose();Refresh-Inventory})
$refresh=Button $p 'Archiv prüfen' 754 283 130;$refresh.Add_Click({Refresh-Inventory -IncludeNetwork})
$script:Inventory=New-Object Windows.Forms.ListView;$script:Inventory.View='Details';$script:Inventory.FullRowSelect=$true;$script:Inventory.Location=New-Object Drawing.Point(24,322);$script:Inventory.Size=New-Object Drawing.Size(860,177)
$null=$script:Inventory.Columns.Add('Modell',380);$null=$script:Inventory.Columns.Add('Vorhandene Dateien',450);$p.Controls.Add($script:Inventory)
$null=Label $p 'Automatisch wird nur lokal nach Dateien gesucht. Netzbestände mit "Archiv prüfen" abfragen. WSL-Modelle werden bei der Ausführung berücksichtigt.' 24 505 860 48

# 2: catalogue models; visible HF token on purpose, shared audio always included.
$p=$script:Pages[1]
$null=Label $p 'Modelle auswählen' 24 18 850 32
$script:ModelOrder=@($script:Catalog.PSObject.Properties | ForEach-Object {$_.Name})
$script:ModelChecks=@{};$y=59
foreach($id in $script:ModelOrder){
    $m=$script:Catalog.PSObject.Properties[$id].Value
    $checked=$id -eq $script:ModelOrder[0];if($script:Previous){$checked=$id -in $script:Previous.Models}
    $c=Check $p ($m.label+'  ·  '+[math]::Round($m.files[0].bytes/1GB,1)+' GiB') $y $checked
    $script:ModelChecks[$id]=$c
    $null=Label $p $m.description 44 ($y+32) 820 44
    $c.Add_CheckedChanged({Update-DefaultModels;Update-ParallelModels})
    $y+=87
}
$null=Label $p 'Whisper large-v3 und pyannote Community-1 werden zusätzlich vorbereitet (ca. 5,8 GiB).' 24 ($y+2) 860 30
$null=Label $p 'Standardmodell für Anfragen' 24 ($y+42) 350 28
$script:Default=Combo $p 390 ($y+39) 494
$null=Label $p 'Hugging-Face-Read-Token (wie gewünscht sichtbar)' 24 ($y+86) 850 26
$script:HfToken=TextBox $p '' 24 ($y+116) 860
$script:HfToken.UseSystemPasswordChar=$false
if($script:Previous -and $script:Previous.TokenFile -and (Test-Path -LiteralPath $script:Previous.TokenFile)){$script:HfToken.Text=(Get-Content -LiteralPath $script:Previous.TokenFile -Raw).Trim()}
$null=Label $p 'Der Zugriff wird geprüft. Die Bedingungen für pyannote Community-1 müssen im HF-Konto akzeptiert sein.' 24 ($y+157) 850 40
$link=New-Object Windows.Forms.LinkLabel;$link.Text='pyannote-Modellseite öffnen';$link.Location=New-Object Drawing.Point(24,($y+202));$link.Size=New-Object Drawing.Size(400,26);$p.Controls.Add($link)
$link.Add_LinkClicked({Start-Process 'https://huggingface.co/pyannote/speaker-diarization-community-1'})
$savedModelOptions=Get-ModelOptions $script:Previous
$script:VerifyFiles=Check $p 'Modelldateien per Prüfsumme prüfen' ($y+234) $savedModelOptions.VerifyModelFiles
$null=Label $p 'Abgewählt: nur Vorhandensein und Dateigröße prüfen; keine vollständigen Prüfsummenläufe. Die synthetische Serverprüfung ist separat wählbar.' 44 ($y+268) 820 46
$script:RecheckModels=Check $p 'Erneut vollständig prüfen (gespeicherte Prüfergebnisse ignorieren)' ($y+319)
$script:RecheckModels.Enabled=$script:VerifyFiles.Checked
$script:VerifyFiles.Add_CheckedChanged({$script:RecheckModels.Enabled=$script:VerifyFiles.Checked;if(-not $script:VerifyFiles.Checked){$script:RecheckModels.Checked=$false}})

# 3: memory and GPU are separate controls with the Windows reserve visible.
$p=$script:Pages[2]
$null=Label $p 'Grafikkarte, Parallelmodell und WSL-Speicher' 24 18 850 34
$null=Label $p 'NVIDIA-Grafikkarte' 24 65 300 26
$script:Gpu=Combo $p 330 62 554
if($script:Hardware){foreach($g in $script:Hardware.Gpus){$null=$script:Gpu.Items.Add(('{0}: {1} — {2:N1} GiB VRAM' -f $g.Index,$g.Name,($g.VramMiB/1024)))};if($script:Gpu.Items.Count){$script:Gpu.SelectedIndex=0}}
$null=Label $p 'WSL-RAM-Obergrenze' 24 117 300 26
$script:Ram=Combo $p 330 114 554
foreach($entry in @('16 GiB — Parallelbetrieb / serieller Sparbetrieb','24 GiB — Empfehlung seriell 9B Q4','28 GiB — seriell 9B Q6 / Gemma 12B Q8','32 GiB — seriell Qwen 27B / Gemma 26B Q4')){$null=$script:Ram.Items.Add($entry)}
$script:Ram.SelectedIndex=1
$script:Reserve=Label $p '' 24 158 860 42
$null=Label $p 'Das Limit gilt benutzerweit für WSL2. Bestehende .wslconfig-Einstellungen werden erhalten und gesichert; laufende andere WSL-Instanzen müssen vorher geschlossen werden.' 24 205 860 50
$null=Label $p 'Parallel vorgehaltenes Modell' 24 277 300 26
$script:Parallel=Combo $p 330 274 554
$script:ParallelIds=@('')
$null=Label $p 'Dieses LLM bleibt gemeinsam mit Whisper und pyannote geladen. Alle weiteren ausgewählten Modelle werden seriell ausgeführt. Die Liste enthält nur Modelle mit passendem Parallelprofil für die gewählte GPU.' 24 314 860 54
$script:DiskCache=Check $p 'Zusätzlicher Sparmodus: Whisper/CT2 bei Modellwechsel auch von SSD nachladen' 375
$null=Label $p 'Normal: Audio bleibt im RAM; bei wenig RAM wird der LLM-Dateicache verworfen. Für 27B unter 24 GiB WSL ist der zusätzliche Whisper-Sparmodus erforderlich.' 44 410 820 54
$null=Label $p '32k Kontext, ein LLM-Slot. Parallel bedeutet gleichzeitig geladen. Nach einer seriellen Verarbeitung wird das hier gewählte Parallelmodell wieder geladen. Das Standardmodell für Anfragen wird separat ausgewählt.' 24 480 860 62
$null=Label $p 'Installationsverzeichnis (enthält die eigene WSL-Umgebung und aktive Laufzeitmodelle)' 24 550 850 26
$installDefault=$script:InstalledRoot;if($script:Previous){$installDefault=$script:Previous.InstallDirectory}
$script:InstallPath=TextBox $p $installDefault 24 580 718
$b=Button $p 'Wählen …' 754 578 130;$b.Add_Click({Browse-Folder $script:InstallPath})
$script:Ram.Add_SelectedIndexChanged({Update-Reserve})
$script:Gpu.Add_SelectedIndexChanged({Update-ParallelModels})

# 4: explicit interface selection, local default and manually started server.
$p=$script:Pages[3]
$null=Label $p 'Server-Erreichbarkeit und Startverhalten' 24 18 850 34
$script:Local=Radio $p 'Nur auf diesem Rechner: localhost' 66 $true
$script:Lan=Radio $p 'Zusätzlich über eine ausgewählte Netzwerk-IP erreichbar' 104
$script:Address=Combo $p 44 150 840
if($script:Hardware){foreach($a in $script:Hardware.Addresses){$null=$script:Address.Items.Add(($a.IPAddress+' — '+$a.InterfaceAlias))};if($script:Address.Items.Count){$script:Address.SelectedIndex=0}}
$script:Address.Enabled=$false;$script:Lan.Add_CheckedChanged({$script:Address.Enabled=$script:Lan.Checked})
$null=Label $p 'Netzwerkfreigabe: TCP 8185, ausgewählte IP und lokales Subnetz, unabhängig vom Windows-Netzwerkprofil. Interne KI-Dienste bleiben an localhost. Administratorrechte werden für die Netzwerkfreigabe angefordert.' 44 197 820 74
$script:Autostart=Check $p 'Server nach meiner Windows-Anmeldung automatisch starten' 304
$script:StartAfter=Check $p 'Server nach Installation und Prüfung eingeschaltet lassen' 346
$script:Verify=Check $p 'Abschließende Prüfung: synthetisches Audio, alle gewählten Modelle und Modellwechsel' 388 $true
$script:CleanupStages=Check $p 'Nach Erfolg zusätzliche lokale Modell-Zwischenkopien bereinigen?' 438 $savedModelOptions.CleanupModelStaging
$null=Label $p 'Abgewählt: für spätere Drüberinstallation behalten. Aktive WSL-Modelle und Ihr Modellarchiv bleiben erhalten. Bei Abbruch werden Zwischenkopien behalten.' 44 478 820 58
$null=Label $p 'Ohne Einschalten am Ende bleibt der Server gestoppt. Start, Stopp und Status finden Sie im Startmenü unter „kienzledoku Server“. Der Arbeitsplatzclient wird separat installiert.' 24 550 860 70

# 5: concrete summary; token deliberately omitted from persisted configuration.
$p=$script:Pages[4]
$null=Label $p 'Zusammenfassung' 24 18 850 32
$script:Summary=TextBox $p '' 24 62 860 458 $true;$script:Summary.ReadOnly=$true;$script:Summary.ScrollBars='Vertical';$script:Summary.BackColor=[Drawing.Color]::FromArgb(248,250,251)
$null=Label $p 'Für WSL und Laufzeitpakete wird Internet benötigt. Neue oder veränderte Modellgewichte werden vollständig geprüft; erfolgreiche Nachweise werden wiederverwendet. Zur Prüfung werden synthetische Daten verwendet.' 24 531 860 58

# 6/7: asynchronous progress and a useful final result, including client connection.
$p=$script:Pages[5]
$null=Label $p 'Installation / Download läuft' 24 18 850 32
$script:ProgressLabel=Label $p '' 24 65 860 70
$script:Bar=New-Object Windows.Forms.ProgressBar;$script:Bar.Location=New-Object Drawing.Point(24,144);$script:Bar.Size=New-Object Drawing.Size(860,24);$p.Controls.Add($script:Bar)
$script:LogView=TextBox $p '' 24 190 860 360 $true;$script:LogView.ReadOnly=$true;$script:LogView.ScrollBars='Vertical';$script:LogView.Font=New-Object Drawing.Font('Consolas',9)
$p=$script:Pages[6]
$script:ResultTitle=Label $p '' 24 18 850 36;$script:ResultTitle.Font=New-Object Drawing.Font('Segoe UI',16,[Drawing.FontStyle]::Bold)
$script:Result=TextBox $p '' 24 65 860 200 $true;$script:Result.ReadOnly=$true;$script:Result.ScrollBars='Vertical'
$null=Label $p 'Installationsprotokoll — bleibt bis zum Schließen sichtbar' 24 278 590 28
$openLog=Button $p 'Ganzes Protokoll öffnen' 635 274 249
$openLog.Add_Click({$log=Join-Path $script:State 'installation.log';if(Test-Path -LiteralPath $log){Start-Process 'notepad.exe' -ArgumentList ('"'+$log+'"')}})

function Selected-Models { $script:ModelOrder | Where-Object {$script:ModelChecks[$_].Checked} }
function Selected-ParallelModel {
    if($script:Parallel.SelectedIndex -lt 0){return ''}
    return [string]$script:ParallelIds[$script:Parallel.SelectedIndex]
}
function Update-ParallelModels([string]$Preferred='__keep__') {
    if(-not $script:Parallel){return}
    if($Preferred -eq '__keep__'){$Preferred=Selected-ParallelModel}
    $script:Parallel.Items.Clear();$script:ParallelIds=@('')
    $null=$script:Parallel.Items.Add('Keines — alle LLMs seriell')
    if($script:Hardware -and $script:Gpu.SelectedIndex -ge 0){
        $g=$script:Hardware.Gpus[$script:Gpu.SelectedIndex]
        foreach($id in @(Get-ParallelModelChoices $script:Catalog @(Selected-Models) $g.VramMiB)){
            $script:ParallelIds+=,$id
            $null=$script:Parallel.Items.Add($script:Catalog.PSObject.Properties[$id].Value.label+' ('+$id+')')
        }
    }
    $index=[Array]::IndexOf($script:ParallelIds,$Preferred)
    $script:Parallel.SelectedIndex=[math]::Max(0,$index)
}
function Source-Roots { @($script:Cache.Text.Trim())+@($script:Sources.Lines | ForEach-Object {$_.Trim()} | Where-Object {$_}) }
function Refresh-Inventory([switch]$IncludeNetwork) {
    $script:Inventory.Items.Clear()
    try{
        $sources=@(Source-Roots);$network=@($sources | Where-Object {Test-NetworkPath $_})
        if(-not $IncludeNetwork){$sources=@($sources | Where-Object {-not(Test-NetworkPath $_)})}
        $sources=@((Join-Path $script:InstallPath.Text 'models'))+$sources
        foreach($row in @(Get-Inventory $script:Root $sources)){
            if(-not $IncludeNetwork -and $network.Count -and $row.State -eq 'fehlt'){$row.State='lokal nicht gefunden; Netzarchiv noch nicht geprüft'}
            $item=New-Object Windows.Forms.ListViewItem($row.Label);$null=$item.SubItems.Add($row.State);$null=$script:Inventory.Items.Add($item)}
    }catch{$null=$script:Inventory.Items.Add('Quellverzeichnisse prüfen: '+$_.Exception.Message)}
}
function Update-DefaultModels {
    if(-not $script:Default){return}
    $previous=$script:Default.SelectedItem
    $script:Default.Items.Clear();foreach($id in @(Selected-Models)){$null=$script:Default.Items.Add($id)}
    if($previous -and $script:Default.Items.Contains($previous)){$script:Default.SelectedItem=$previous}
    elseif($script:Default.Items.Count){$script:Default.SelectedIndex=0}
}
function Update-Reserve {
    if(-not $script:Hardware){$script:Reserve.Text=$hardwareMessage;return}
    $values=@(16,24,28,32);$budget=$values[$script:Ram.SelectedIndex]
    $total=$script:Hardware.RamBytes/1GB;$remaining=$total-$budget
    $script:Reserve.Text=('Gesamter RAM: {0:N1} GiB | WSL maximal: {1} GiB | Für Windows eingeplant: ca. {2:N1} GiB' -f $total,$budget,$remaining)
    $script:Reserve.ForeColor=[Drawing.Color]::DarkGreen;if($remaining -lt 4){$script:Reserve.ForeColor=[Drawing.Color]::Firebrick}
}
function Build-Config {
    $models=@(Selected-Models);if(-not $models.Count){throw 'Mindestens ein Modell auswählen.'}
    if(-not $script:HfToken.Text.Trim()){throw 'Hugging-Face-Token eingeben.'}
    $cache=[IO.Path]::GetFullPath($script:Cache.Text.Trim())
    if(-not [IO.Path]::IsPathRooted($cache)){throw 'Absolutes Modellverzeichnis erforderlich.'}
    $values=@(16,24,28,32);$gpuIndex=0
    $network='local';$address='';if($script:Lan.Checked){$network='lan';if(-not $script:Address.SelectedItem){throw 'Netzwerk-IP auswählen.'};$address=($script:Address.SelectedItem -split ' — ')[0]}
    $audio='ram';if($script:DiskCache.Checked){$audio='disk'}
    $cfg=[ordered]@{Version=$script:InstallerVersion;Models=$models;DefaultModel=[string]$script:Default.SelectedItem;
        WslRamGiB=$values[$script:Ram.SelectedIndex];Mode='selected';ParallelModel=(Selected-ParallelModel);AudioCache=$audio;
        GpuIndex=$gpuIndex;Profiles=@{};CacheDirectory=$cache;Sources=@(Source-Roots | Select-Object -Skip 1);
        InstallDirectory=[IO.Path]::GetFullPath($script:InstallPath.Text.Trim());StateDirectory=$script:State;
        TokenFile=(Join-Path $script:State 'hf.token');NetworkMode=$network;NetworkAddress=$address;NetworkRemove=$false;
        Autostart=$script:Autostart.Checked;StartAfterInstall=$script:StartAfter.Checked;Verify=$script:Verify.Checked;
        VerifyModelFiles=$script:VerifyFiles.Checked;CleanupModelStaging=$script:CleanupStages.Checked;
        ForceModelVerification=($script:VerifyFiles.Checked -and $script:RecheckModels.Checked)}
    if($script:InstallRadio.Checked){
        if(-not $script:Hardware -or $script:Hardware.Build -lt 22000 -or $script:Hardware.Architecture -ne 'AMD64'){throw 'Windows 11 x64 mit funktionsfähigem NVIDIA-Treiber erforderlich.'}
        if($script:Gpu.SelectedIndex -lt 0){throw 'NVIDIA-GPU fehlt. Windows-Treiber installieren; Downloadmodus bleibt verfügbar.'}
        $g=$script:Hardware.Gpus[$script:Gpu.SelectedIndex];$cfg.GpuIndex=$g.Index
        if(($script:Hardware.RamBytes/1GB)-$cfg.WslRamGiB -lt 3.5){throw 'Etwa 4 GiB Reserve für Windows erforderlich. Kleinere WSL-Stufe auswählen.'}
        if(Test-NetworkPath $cfg.InstallDirectory){throw 'Aktive WSL-Umgebung auf einem lokalen Laufwerk installieren. Netzlaufwerke sind als Modellquelle erlaubt.'}
        $cfg.Profiles=Get-ProfilePlan $script:Catalog $models $cfg.DefaultModel $cfg.Mode $g.VramMiB $cfg.WslRamGiB $audio $cfg.ParallelModel
    }
    return $cfg
}
function Show-Page([int]$Index){
    $script:Pages[$script:Page].Visible=$false;$script:Page=$Index;$script:Pages[$Index].Visible=$true;$script:Pages[$Index].BringToFront()
    $script:Back.Enabled=$Index -gt 0 -and $Index -lt 5
    $script:Next.Visible=$Index -lt 5;$script:Cancel.Enabled=$Index -ne 5
    $script:Next.Text='Weiter';if($Index -eq 4){$script:Next.Text='Jetzt ausführen'}
    $labels=@('Start und vorhandene Modelle','Modelle und Hugging Face','Hardware und WSL-Speicher','Netzwerk und Serverstart','Zusammenfassung','Fortschritt','Ergebnis')
    $script:Step.Text=$labels[$Index]
}
$script:Next.Add_Click({
    try{
        switch($script:Page){
            0{Refresh-Inventory;Show-Page 1}
            1{if(-not @(Selected-Models).Count){throw 'Mindestens ein Modell auswählen.'};if($script:DownloadRadio.Checked){$script:Cfg=Build-Config;Prepare-Summary;Show-Page 4}else{Update-Reserve;Show-Page 2}}
            2{if($script:Gpu.SelectedIndex -lt 0){throw 'NVIDIA-Treiber/GPU fehlt.'};Show-Page 3}
            3{$script:Cfg=Build-Config;Prepare-Summary;Show-Page 4}
            4{Start-Operation}
        }
    }catch{
        $failure=$_;$message=$failure.Exception.Message
        # Failures before the engine starts (including private-file permissions)
        # must also leave a useful log, without recording the visible HF token.
        try {
            [IO.Directory]::CreateDirectory($script:State)|Out-Null
            $detail='[{0}] Installer {1}: {2}; Fehlerkennung: {3}; Aufrufstelle: {4}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$script:InstallerVersion,$message,$failure.FullyQualifiedErrorId,$failure.ScriptStackTrace
            $secret=$script:HfToken.Text.Trim()
            if($secret){$detail=$detail.Replace($secret,'[Token ausgelassen]');$message=$message.Replace($secret,'[Token ausgelassen]')}
            Add-Content -LiteralPath (Join-Path $script:State 'installation.log') -Value $detail -Encoding UTF8
        }catch{}
        [Windows.Forms.MessageBox]::Show($message,'Bitte prüfen','OK','Warning')|Out-Null
    }
})
$script:Back.Add_Click({$next=$script:Page-1;if($script:Page -eq 4 -and $script:DownloadRadio.Checked){$next=1};Show-Page $next})
function Request-AdminRetryCancellation {
    $path=Get-AdminRetryCancelPath $script:Cfg
    if(-not $path){return}
    [IO.File]::WriteAllText($path,'cancel',(New-Object Text.UTF8Encoding($false)));Set-PrivateFile $path
    $script:AdminCancelSent=$true;$script:CanCancelAdminRetry=$false
    $script:Cancel.Enabled=$false;$script:Cancel.Text='Abbruch läuft'
    $script:ProgressLabel.Text='Installation wird abgebrochen; bereits übernommene Modelle bleiben erhalten.'
}
$script:Cancel.Add_Click({if($script:Busy -and $script:CanCancelAdminRetry){Request-AdminRetryCancellation}else{$script:Form.Close()}})
$script:Form.Add_FormClosing({param($sender,$eventArgs)if($script:Busy){$eventArgs.Cancel=$true;if($script:CanCancelAdminRetry){Request-AdminRetryCancellation}else{[Windows.Forms.MessageBox]::Show('Der Vorgang läuft. Warten Sie auf das Ergebnis. Zwischen wiederholten Administratorabfragen können Sie mit Abbrechen beenden.','Vorgang läuft')|Out-Null}}})
function Prepare-Summary {
    $cfg=$script:Cfg;$action='Server installieren';if($script:DownloadRadio.Checked){$action='Nur Modelle herunterladen'}
    $text="$action`r`n`r`nModelle: $($cfg.Models -join ', ')`r`nStandardmodell für Anfragen: $($cfg.DefaultModel)`r`nModellarchiv: $($cfg.CacheDirectory)`r`nWeitere Quellen: $($cfg.Sources -join '; ')`r`nWhisper und pyannote: enthalten`r`nPrüfsummenprüfung der Modelle: $($cfg.VerifyModelFiles)`r`n"
    if($script:InstallRadio.Checked){
        $parallelLabel='Keines — alle LLMs seriell';if($cfg.ParallelModel){$parallelLabel=$script:Catalog.PSObject.Properties[$cfg.ParallelModel].Value.label}
        $text+="`r`nParallel vorgehalten: $parallelLabel`r`nInstallation: $($cfg.InstallDirectory)`r`nWSL-RAM-Obergrenze: $($cfg.WslRamGiB) GiB`r`nAudiocache: $($cfg.AudioCache)`r`n"
        foreach($id in $cfg.Models){$text+="$id : $($cfg.Profiles[$id].Mode)`r`n"}
        $text+="`r`nErreichbarkeit: localhost";if($cfg.NetworkMode -eq 'lan'){$text+=' und '+$cfg.NetworkAddress}
        $text+="`r`nPort: 8185`r`nAutostart nach Anmeldung: $($cfg.Autostart)`r`nAm Ende eingeschaltet: $($cfg.StartAfterInstall)`r`nSynthetische Serverprüfung: $($cfg.Verify)`r`nZwischenkopien nach Erfolg bereinigen: $($cfg.CleanupModelStaging)`r`n`r`nDie eigene WSL-Instanz heißt kienzledoku-server. WSL-Aktivierung kann einen Neustart erfordern. Erforderliche Administratorrechte werden separat angefordert. Bestehende Clientinstallationen werden nicht verändert."
    }
    $script:Summary.Text=$text
}
function Start-Operation {
    $script:Cfg=Build-Config
    $script:Cfg['AdminRetryId']=[guid]::NewGuid().ToString('N')
    $script:AdminCancelSent=$false;$script:CanCancelAdminRetry=$false
    [IO.Directory]::CreateDirectory($script:State)|Out-Null
    $config=Join-Path $script:State 'pending-install.json'
    Write-Json $config $script:Cfg;Set-PrivateFile $config
    [IO.File]::WriteAllText($script:Cfg.TokenFile,$script:HfToken.Text.Trim(),(New-Object Text.UTF8Encoding($false)));Set-PrivateFile $script:Cfg.TokenFile
    Remove-Item -LiteralPath (Join-Path $script:State 'progress.json') -Force -ErrorAction SilentlyContinue
    $operation='Install';if($script:DownloadRadio.Checked){$operation='Download'}
    $arguments='-NoProfile -ExecutionPolicy Bypass -File "{0}" -Action {1} -ConfigPath "{2}"' -f (Join-Path $PSScriptRoot 'Engine.ps1'),$operation,$config
    $runId=(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
    $script:StdoutPath=Join-Path $script:State ('engine-'+$runId+'.stdout.log')
    $script:StderrPath=Join-Path $script:State ('engine-'+$runId+'.stderr.log')
    foreach($path in @($script:StdoutPath,$script:StderrPath)){[IO.File]::WriteAllText($path,'');Set-PrivateFile $path}
    $script:Process=Start-Process -FilePath (Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $script:StdoutPath -RedirectStandardError $script:StderrPath
    $null=$script:Process.Handle # Retain the child handle before it can exit.
    Write-Json (Join-Path $script:State 'last-operation.json') @{Version=$script:InstallerVersion;Pid=$script:Process.Id;StartedAt=(Get-Date).ToString('o');StdoutPath=$script:StdoutPath;StderrPath=$script:StderrPath}
    $script:Busy=$true;Show-Page 5;$script:Timer.Start()
}
function Update-AdminRetryCancelControl([string]$Phase) {
    $script:CanCancelAdminRetry=$script:Busy -and $Phase -eq 'admin_wait' -and -not $script:AdminCancelSent
    if($script:AdminCancelSent){$script:Cancel.Text='Abbruch läuft';$script:Cancel.Enabled=$false}
    elseif($script:CanCancelAdminRetry){$script:Cancel.Text='Abbrechen';$script:Cancel.Enabled=$true}
    else{$script:Cancel.Text='Schließen';$script:Cancel.Enabled=$true}
}
$script:Timer=New-Object Windows.Forms.Timer;$script:Timer.Interval=700
$script:Timer.Add_Tick({
    try{
        $path=Join-Path $script:State 'progress.json'
        if(Test-Path -LiteralPath $path){try{$progress=Read-Json $path;$script:ProgressLabel.Text=$progress.Message;$script:Bar.Value=[math]::Max(0,[math]::Min(100,$progress.Percent));Update-AdminRetryCancelControl $progress.Phase}catch{}}
        $log=Join-Path $script:State 'installation.log'
        if(Test-Path -LiteralPath $log){try{$script:LogView.Text=((Get-Content -LiteralPath $log -Tail 55 -Encoding UTF8) -join "`r`n").Replace([string][char]0,'');$script:LogView.SelectionStart=$script:LogView.Text.Length;$script:LogView.ScrollToCaret()}catch{}}
        if($script:Process.HasExited){
            $script:Busy=$false;$script:CanCancelAdminRetry=$false;$script:AdminCancelSent=$false
            $script:Cancel.Text='Schließen';$script:Cancel.Enabled=$true;$progress=$null
            if(Test-Path -LiteralPath $path){try{$progress=Read-Json $path}catch{}}
            $exitCode=Get-FinishedProcessExitCode $script:Process
            $result=Get-OperationResult $progress $exitCode $script:StderrPath $script:StdoutPath $script:HfToken.Text.Trim()
            $success=$result.Success;$message=$result.Message
            if(-not $success){
                try{Add-Content -LiteralPath $log -Encoding UTF8 -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$message)}catch{}
                if($result.UnexpectedExit){$result | Add-Member -NotePropertyName Percent -NotePropertyValue 0;try{Write-Json $path $result}catch{}}
            }
            $script:ResultTitle.Text='Vorgang fehlgeschlagen / unterbrochen';if($success){$script:ResultTitle.Text='Vorgang abgeschlossen'}
            if($result.RestartRequired){$script:ResultTitle.Text='Windows-Neustart erforderlich'}
            $text=$message+"`r`n`r`nModellarchiv: "+$script:Cfg.CacheDirectory+"`r`nProtokoll: "+$log
            if(-not $success){$text+="`r`nProzess-Fehlerausgabe: "+$script:StderrPath+"`r`nProzess-Standardausgabe: "+$script:StdoutPath}
            if($success -and $script:InstallRadio.Checked){
                $text+="`r`n`r`nLokale Serveradresse: http://localhost:8185"
                if($script:Cfg.NetworkMode -eq 'lan'){$text+="`r`nNetzwerkadresse: http://$($script:Cfg.NetworkAddress):8185`r`nLAN-Freigabe eingerichtet; Endpunkt auf diesem Rechner geprüft. Zugriff vom Client separat prüfen."}
                $clientFile=Join-Path $script:State 'client.token'
                if(Test-Path -LiteralPath $clientFile){$text+="`r`n`r`nClient-Zugangstoken (für den separat installierten Client):`r`n"+(Get-Content -LiteralPath $clientFile -Raw)}
                $text+="`r`n`r`nServer am Ende eingeschaltet: $($script:Cfg.StartAfterInstall)`r`nSynthetische Serverprüfung ausgeführt: $($script:Cfg.Verify)`r`nModell-Prüfsummenprüfung: $($script:Cfg.VerifyModelFiles)`r`nZwischenkopien bereinigen gewählt: $($script:Cfg.CleanupModelStaging)`r`nStart / Stopp / Status / Prüfung: Startmenü > kienzledoku Server"
            }
            if(-not $success){$text+="`r`n`r`nNach einem notwendigen Neustart: Startmenü > kienzledoku Server > Installation fortsetzen. Alternativ dieselbe Setup-EXE erneut öffnen. Modelle und fertige Phasen werden wiederverwendet."}
            $script:Result.Text=$text
            # Keep the very same log control, including its contents, visible.
            $script:Pages[6].Controls.Add($script:LogView)
            $script:LogView.Location=New-Object Drawing.Point(24,315);$script:LogView.Size=New-Object Drawing.Size(860,240)
            try{$script:LogView.Text=((Get-Content -LiteralPath $log -Tail 120 -Encoding UTF8) -join "`r`n").Replace([string][char]0,'')}catch{}
            $script:LogView.SelectionStart=$script:LogView.Text.Length;$script:LogView.ScrollToCaret()
            Show-Page 6;$script:Timer.Stop()
        }
    }catch{$script:ProgressLabel.Text='Fortschritt wird aktualisiert …'}
})
Update-DefaultModels
if($script:Previous){
    $script:Default.SelectedItem=$script:Previous.DefaultModel
    $script:Ram.SelectedIndex=[Array]::IndexOf(@(16,24,28,32),[int]$script:Previous.WslRamGiB)
    $script:DiskCache.Checked=$script:Previous.AudioCache -eq 'disk';$script:Autostart.Checked=$script:Previous.Autostart;$script:StartAfter.Checked=$script:Previous.StartAfterInstall;$script:Verify.Checked=$script:Previous.Verify
    if($script:Previous.NetworkMode -eq 'lan'){$script:Lan.Checked=$true;foreach($entry in $script:Address.Items){if($entry.StartsWith($script:Previous.NetworkAddress+' — ')){$script:Address.SelectedItem=$entry;break}}}
}
$preferred=[string]$script:Default.SelectedItem
if($script:Previous){
    $preferred=''
    if($script:Previous.PSObject.Properties['ParallelModel']){$preferred=[string]$script:Previous.ParallelModel}
    elseif($script:Previous.Mode -ne 'serial'){
        $previousDefaultModelId=[string]$script:Previous.DefaultModel
        $property=$script:Previous.Profiles.PSObject.Properties[$previousDefaultModelId]
        if($property -and $property.Value.Mode -eq 'parallel'){$preferred=$previousDefaultModelId}
    }
}
Update-ParallelModels $preferred
Update-Reserve;Refresh-Inventory;Show-Page 0
$null=$script:Form.ShowDialog()
$script:Timer.Dispose();$script:Form.Dispose()
$script:WizardMutex.ReleaseMutex();$script:WizardMutex.Dispose()
