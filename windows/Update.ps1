# Whole-tree replacement. Models, configuration and credentials are outside these code roots.
function Assert-CodePath([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path)
    if($full -eq [IO.Path]::GetPathRoot($full)){throw 'Kein Installationsverzeichnis angegeben.'}
    $part=$full
    while($part){
        if(Test-Path -LiteralPath $part){
            if((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Verknüpfte Installationspfade werden nicht verändert.'}
        }
        $part=[IO.Path]::GetDirectoryName($part)
    }
    return $full
}
function Get-CodeInventory([string]$Root) {
    $files=@{}
    foreach($entry in Get-ChildItem -LiteralPath $Root -Recurse -Force){
        if($entry.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Verknüpfung in Programmnutzlast; Update abgebrochen.'}
        $relative=$entry.FullName.Substring($Root.Length).TrimStart([char[]]'\/').Replace('\','/')
        if(!$entry.PSIsContainer -and $relative -ne '.kienzledoku-payload.json' -and $relative -notmatch '(^|/)__pycache__/|\.pyc$'){
            $files[$relative]=(Get-FileHash -LiteralPath $entry.FullName -Algorithm SHA256).Hash
        }
    }
    return $files
}
function Assert-CodeInventory([string]$Root) {
    $null=Assert-CodePath $Root
    $expected=Get-Content -LiteralPath (Join-Path $Root '.kienzledoku-payload.json') -Raw | ConvertFrom-Json
    $actual=Get-CodeInventory $Root
    $names=@($expected.PSObject.Properties.Name)
    if($names.Count -ne $actual.Count){throw 'Zusätzliche oder fehlende Programmdateien; Update nicht abgeschlossen.'}
    foreach($name in $names){if($actual[$name] -ne $expected.$name){throw 'Programmdateien stimmen nicht mit der neuen Nutzlast überein.'}}
}
function Start-CodeUpdate([string]$Source,[string]$Target,[string]$Marker,[string[]]$Names=@()) {
    $sourcePath=Assert-CodePath $Source;$targetPath=Assert-CodePath $Target
    if($sourcePath -eq $targetPath){throw 'Für ein Update den neuen Installer außerhalb des installierten Programmverzeichnisses starten.'}
    foreach($pair in @(@($sourcePath,$targetPath),@($targetPath,$sourcePath))){
        if($pair[0].StartsWith($pair[1]+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Quelle und Ziel dürfen nicht ineinander liegen.'}
    }
    if(!(Test-Path -LiteralPath (Join-Path $sourcePath $Marker) -PathType Leaf)){throw 'Neue Programmnutzlast unvollständig.'}
    if((Test-Path -LiteralPath $targetPath) -and !(Test-Path -LiteralPath (Join-Path $targetPath $Marker) -PathType Leaf)){throw 'Ziel ist keine bekannte Kienzledoku-Installation.'}
    $parent=[IO.Path]::GetDirectoryName($targetPath)
    $null=[IO.Directory]::CreateDirectory($parent)
    $work=Join-Path $parent ('.kienzledoku-update-'+[guid]::NewGuid().ToString('N'))
    $candidate=Join-Path $work 'candidate';$previous=Join-Path $work 'previous'
    $null=[IO.Directory]::CreateDirectory($candidate)
    @{Schema=1;Target=$targetPath;Marker=$Marker}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $work 'transaction.json') -Encoding UTF8
    try {
        $null=Get-CodeInventory $sourcePath
        $items=if($Names.Count){@($Names|ForEach-Object {Get-Item -LiteralPath (Join-Path $sourcePath $_)})}else{@(Get-ChildItem -LiteralPath $sourcePath -Force)}
        foreach($item in $items){Copy-Item -LiteralPath $item.FullName -Destination $candidate -Recurse -Force}
        Get-CodeInventory $candidate|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $candidate '.kienzledoku-payload.json') -Encoding UTF8
        Assert-CodeInventory $candidate
        if(Test-Path -LiteralPath $targetPath){Move-Item -LiteralPath $targetPath -Destination $previous}
        try{Move-Item -LiteralPath $candidate -Destination $targetPath}catch{if(Test-Path -LiteralPath $previous){Move-Item -LiteralPath $previous -Destination $targetPath};throw}
    } catch {
        # If restoration failed too, this is the only remaining old program tree.
        if(!(Test-Path -LiteralPath $previous)){Remove-Item -LiteralPath $work -Recurse -Force}
        throw
    }
    return @{Work=$work;Target=$targetPath;Marker=$Marker}
}
function Undo-CodeUpdate($Transaction) {
    if(!$Transaction){return}
    $null=Assert-CodePath $Transaction.Work;$null=Assert-CodePath $Transaction.Target
    $null=Get-CodeInventory $Transaction.Target
    Remove-Item -LiteralPath $Transaction.Target -Recurse -Force
    $previous=Join-Path $Transaction.Work 'previous'
    if(Test-Path -LiteralPath $previous){Move-Item -LiteralPath $previous -Destination $Transaction.Target}
    Remove-Item -LiteralPath $Transaction.Work -Recurse -Force
}
function Complete-CodeUpdate($Transaction) {
    if(!$Transaction){return}
    Assert-CodeInventory $Transaction.Target
    $parent=[IO.Path]::GetDirectoryName($Transaction.Target)
    $obsolete=@()
    foreach($folder in Get-ChildItem -LiteralPath $parent -Directory -Force -Filter '.kienzledoku-update-*'){
        $null=Assert-CodePath $folder.FullName
        $meta=Get-Content -LiteralPath (Join-Path $folder.FullName 'transaction.json') -Raw|ConvertFrom-Json
        if($meta.Schema -ne 1 -or $meta.Target -ne $Transaction.Target){continue}
        if($meta.Marker -ne $Transaction.Marker -or (Test-Path -LiteralPath (Join-Path $folder.FullName 'candidate'))){throw 'Unvollständiger früherer Updatevorgang; Bereinigung nicht abgeschlossen.'}
        $null=Get-CodeInventory $folder.FullName
        if(@(Get-ChildItem -LiteralPath $folder.FullName -Force|Where-Object {$_.Name -notin @('previous','transaction.json')}).Count){throw 'Unbekannter Inhalt einer Updatesicherung.'}
        $obsolete+=,$folder.FullName
    }
    foreach($folder in $obsolete){Remove-Item -LiteralPath $folder -Recurse -Force}
}
function Assert-ClientClosed([string]$Target) {
    $root=[IO.Path]::GetFullPath($Target).TrimEnd([char[]]'\/')+[IO.Path]::DirectorySeparatorChar
    foreach($process in Get-CimInstance Win32_Process -ErrorAction Stop){
        if($process.ProcessId -eq $PID){continue}
        if(($process.ExecutablePath -and $process.ExecutablePath.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) -or
           ($process.CommandLine -and $process.CommandLine.Contains($root))){
            throw 'Bitte zuerst alle Kienzledoku-Aufnahme- und Einstellungsfenster schließen. Es wird nichts verworfen.'
        }
    }
}
