param([switch]$Network)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Throws([scriptblock]$Body){$thrown=$false;try{& $Body}catch{$thrown=$true};Assert $thrown 'Erwarteter Fehler blieb aus.'}
function Case([string]$Name,[scriptblock]$Body){& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$catalog=Get-Catalog $root
Case 'Installer version comes from the central VERSION file' {
    Assert ((Get-InstallerVersion) -eq [IO.File]::ReadAllText((Join-Path $root 'VERSION')).Trim()) 'Uneinheitliche Installerversion.'
}
Case 'UNC model archives are network paths and the local temp directory is local' {
    Assert (Test-NetworkPath '\\server\share\models') 'UNC-Modellarchiv nicht als Netzwerk erkannt.'
    Assert (-not(Test-NetworkPath ([IO.Path]::GetTempPath()))) 'Lokaler Pfad fälschlich als Netzwerk erkannt.'
}
Case 'Private file ACL uses direct DACL persistence and access-only reads, no audit provider' {
    $tok=$null;$err=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Core.psm1'),[ref]$tok,[ref]$err)
    $function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Set-PrivateFile'},$true)
    $commands=@($function.FindAll({param($node)$node -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object {$_.GetCommandName()})
    Assert ('Set-Acl' -notin $commands -and 'Get-Acl' -notin $commands) 'ACL-Provider kann weiterhin Audit-Sonderrechte verlangen.'
    $calls=@($function.FindAll({param($node)$node -is [Management.Automation.Language.InvokeMemberExpressionAst]},$true))
    Assert (@($calls|Where-Object {$_.Member.Value -eq 'SetAccessControl'}).Count -eq 2) '.NET-Schnittstelle für Desktop/Core fehlt.'
    $reads=@($calls|Where-Object {$_.Member.Value -eq 'GetAccessControl'})
    Assert ($reads.Count -eq 2) 'Dateiberechtigungen werden nicht zurückgelesen.'
    foreach($read in $reads){Assert ($read.Arguments[-1].Extent.Text -eq '[Security.AccessControl.AccessControlSections]::Access') 'Dateiprüfung verlangt unnötig Audit-/Eigentümerrechte.'}
    Assert (@($calls|Where-Object {$_.Member.Value -in @('SetOwner','SetGroup','SetAuditRule','AddAuditRule','SetAuditRuleProtection')}).Count -eq 0) 'Private Dateien dürfen nur Zugriffsrechte ändern.'
}
Case 'Automatic GPU profiles and unsupported resident 27B' {
    $plan=Get-ProfilePlan $catalog @('9b-q4','9b-q6','27b-q4') '9b-q4' auto 24576 32
    Assert ($plan['9b-q4'].Mode -eq 'parallel' -and $plan['9b-q6'].Mode -eq 'parallel') '9B-Parallelprofile fehlen.'
    Assert ($plan['27b-q4'].Mode -eq 'serial') '27B darf nicht parallel starten.'
    Throws {Get-ProfilePlan $catalog @('27b-q4') '27b-q4' parallel 32768 32}
    Throws {Get-ProfilePlan $catalog @('9b-q6') '9b-q6' parallel 16384 24}
}
Case 'Serial GPU checks and low memory audio policy' {
    $plan=Get-ProfilePlan $catalog @('9b-q4') '9b-q4' auto 8192 16
    Assert ($plan['9b-q4'].Mode -eq 'serial' -and $plan['9b-q4'].AudioCache -eq 'ram') '16-GiB-Audiocache falsch.'
    Throws {Get-ProfilePlan $catalog @('9b-q6') '9b-q6' serial 8192 24}
    Throws {Get-ProfilePlan $catalog @('27b-q4') '27b-q4' serial 24576 16 ram}
    $plan=Get-ProfilePlan $catalog @('27b-q4') '27b-q4' serial 24576 16 disk
    Assert ($plan['27b-q4'].AudioCache -eq 'disk') '27B-Sparprofil falsch.'
}
Case 'WSL limit above 50 percent preserves unrelated settings and sections' {
    $old="[wsl2]`nprocessors=6`nmemory=8GB`nswap=0`n[experimental]`nautoMemoryReclaim=gradual`n"
    $new=Set-WslMemoryText $old 24
    Assert ($new.Contains('memory=24GB')) 'RAM-Limit nicht geändert.'
    Assert ($new.Contains('processors=6') -and $new.Contains('swap=0') -and $new.Contains('autoMemoryReclaim=gradual')) 'Andere WSL-Einstellungen wurden verändert.'
    Assert (([regex]::Matches($new,'memory=')).Count -eq 1) 'Doppeltes RAM-Limit.'
    $new=Set-WslMemoryText '[experimental]' 16
    Assert ($new.Contains('[wsl2]') -and $new.Contains('memory=16GB')) 'Fehlende wsl2-Sektion falsch ergänzt.'
    Throws {Set-WslMemoryText '' 12}
}
Case 'Required files include audio and only selected LLMs' {
    $files=@(Get-RequiredFiles $root @('9b-q4'))
    Assert (@($files|Where-Object {$_.path -like '9b-q4/*'}).Count -eq 1) 'Q4 fehlt.'
    Assert (@($files|Where-Object {$_.path -like '9b-q6/*' -or $_.path -like '27b-q4/*'}).Count -eq 0) 'Nicht ausgewählte Gewichte enthalten.'
    Assert (@($files|Where-Object {$_.path -eq 'whisper/large-v3.pt'}).Count -eq 1) 'Nativer Whisper fehlt.'
    Assert (@($files|Where-Object {$_.path -eq 'pyannote/config.yaml'}).Count -eq 1) 'pyannote fehlt.'
}
Case 'Native process invocation preserves spaces, quotes, Unicode and stderr without false failure' {
    $tok=$null;$err=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Engine.ps1'),[ref]$tok,[ref]$err)
    $function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Native'},$true)
    . ([scriptblock]::Create($function.Extent.Text))
    function Log([string]$Message){$script:NativeLog+=$Message}
    $script:NativeLog=@()
    $python=(Get-Command python3).Source
    $scriptText='import json,sys; print(json.dumps(sys.argv[1:],ensure_ascii=False))'
    $values=@('','--version','-d','space path','ä ö ü','quote"inside','ends\','space tail\','slashes\\"quote')
    $result=Invoke-Native $python (@('-c',$scriptText)+$values) -Capture
    $decoded=@($result|ConvertFrom-Json)
    Assert (($decoded -join '|') -ceq ($values -join '|')) 'Argumente verändert.'
    Invoke-Native $python @('-c','import sys; print("stdout"); sys.stderr.write("progress\n")')
    Assert ('stdout' -in $script:NativeLog -and 'progress' -in $script:NativeLog) 'stderr führt fälschlich zum Fehler.'
    Throws {Invoke-Native $python @('-c','import sys; sys.exit(7)')}
}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-core-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
try{
    Case 'Local SSD-style import with Unicode and spaces verifies Git blob hashes' {
        $source=Join-Path $temporary 'SSD Modelle ä';[IO.Directory]::CreateDirectory($source)|Out-Null
        $path=Join-Path $source 'hello.bin';[IO.File]::WriteAllText($path,"hello`n",(New-Object Text.UTF8Encoding($false)))
        $file=[pscustomobject]@{path='q4/hello.bin';filename='hello.bin';bytes=6;sha256=$null;git_blob_sha1='ce013625030ba8dba906f756967f9e9ca394464a'}
        Assert (Test-ModelFile $path $file -Full) 'Git-Blob-Prüfung schlägt fehl.'
        Assert ((Find-ModelFile @($source) $file -Full) -eq $path) 'Flache SSD-Quelle nicht erkannt.'
        [IO.File]::WriteAllText($path,"other`n",(New-Object Text.UTF8Encoding($false)))
        Assert (-not(Test-ModelFile $path $file -Full)) 'Gleich große beschädigte Datei akzeptiert.'
    }
    Case 'Path traversal and absolute imported model paths are refused' {
        Throws {Get-ContainedPath $temporary '../outside'}
        Throws {Get-ContainedPath $temporary '/absolute'}
        $p=Get-ContainedPath $temporary 'whisper/model.bin'
        Assert ($p.StartsWith($temporary)) 'Normaler Pfad wurde falsch behandelt.'
    }
    Case 'Interrupted download is shown as incomplete at startup' {
        $file=$catalog.'9b-q4'.files[0];$path=Get-ContainedPath $temporary ($file.path+'.part')
        [IO.Directory]::CreateDirectory((Split-Path -Parent $path))|Out-Null
        [IO.File]::WriteAllText($path,'partial')
        $inventory=@(Get-Inventory $root @($temporary))
        Assert (($inventory|Where-Object {$_.Id -eq '9b-q4'}).State -eq 'unvollständig') 'Teilmodell nicht erkannt.'
    }
    Case 'A complete partial file is recovered without any network request' {
        $path=Join-Path $temporary 'complete.bin'
        [IO.File]::WriteAllText(($path+'.part'),"hello`n",(New-Object Text.UTF8Encoding($false)))
        Get-Download 'https://invalid.kienzledoku.invalid/never-requested' $path '' 6
        $file=[pscustomobject]@{bytes=6;sha256=$null;git_blob_sha1='ce013625030ba8dba906f756967f9e9ca394464a'}
        Assert (Test-ModelFile $path $file -Full) 'Vollständige Teildatei nicht wiederhergestellt.'
    }
    if($Network){
        Case 'Real HTTPS download resumes or safely replaces an ignored Range request' {
            $file=@(Read-Json (Join-Path $root 'audio-files.json')|Where-Object {$_.path -eq 'whisper/config.json'})[0]
            $path=Join-Path $temporary 'config.json'
            [IO.File]::WriteAllText(($path+'.part'),'incomplete prefix')
            Get-Download $file.url $path '' $file.bytes
            # Wrong prefix must be detected even when a server honors Range. A
            # resumed file is never trusted merely because the byte count fits.
            if(-not(Test-ModelFile $path $file -Full)){
                Remove-Item -LiteralPath $path -Force
                Get-Download $file.url $path '' $file.bytes
            }
            Assert (Test-ModelFile $path $file -Full) 'Echter Download/Hash ungültig.'
        }
    }
}finally{Remove-Item -LiteralPath $temporary -Recurse -Force}
$tokens=$null;$errors=$null
foreach($file in @(Get-ChildItem (Join-Path $root 'windows') -Recurse -Include *.ps1,*.psm1)+@(Get-ChildItem $PSScriptRoot -Filter *.ps1)){
    $null=[Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors|Out-String)}
}
Write-Output "All $script:Passed core cases passed; all PowerShell sources parse."
