$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$module=Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking -PassThru
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-json-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
try {
    & $module {
        param($Root,$Temporary)
        # Reproduce Windows PowerShell 5.1's cmdlet output on PowerShell 7 too:
        # a top-level JSON array is ONE pipeline object, before Read-Json handles it.
        function script:ConvertFrom-Json {
            [CmdletBinding()]
            param([Parameter(ValueFromPipeline=$true)][string]$InputObject)
            process {
                if((Get-Command Microsoft.PowerShell.Utility\ConvertFrom-Json).Parameters.ContainsKey('NoEnumerate')){
                    $parsed=Microsoft.PowerShell.Utility\ConvertFrom-Json -InputObject $InputObject -NoEnumerate
                } else {$parsed=Microsoft.PowerShell.Utility\ConvertFrom-Json -InputObject $InputObject}
                return ,$parsed
            }
        }
        function script:Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
        $raw=@('[1,2]'|ConvertFrom-Json)
        Assert ($raw.Count -eq 1 -and $raw[0] -is [array]) '5.1 simulation is not active.'

        # Exercise the exact reported call, with no token, model download or network.
        function script:Get-Download([string]$Url,[string]$Destination,[string]$Token,[long]$ExpectedBytes){
            Assert ($ExpectedBytes -eq 444) 'pyannote access check received the wrong byte count.'
            Assert ($Url -like 'https://huggingface.co/pyannote/*/config.yaml') 'Wrong access-check URL.'
            [IO.File]::WriteAllText($Destination,'test response')
        }
        function script:Test-ModelFile([string]$Path,$File,[switch]$Full){
            Assert ($Full -and $File.path -eq 'pyannote/config.yaml') 'Access check selected the wrong file.'
            return $true
        }
        Test-HfAccess 'hf_TestToken' $Root
        Write-Output 'PASS pyannote access check passes one file size to ExpectedBytes'

        $files=@(Get-RequiredFiles $Root @('9b-q4'))
        Assert ($files.Count -eq 12) 'Expected 12 individual model/audio files, not a nested array.'
        foreach($file in $files){
            Assert ($file -isnot [array] -and $file.bytes -isnot [array]) 'File size must be a scalar.'
            Assert ([long]$file.bytes -gt 0) 'Each file must have a positive byte count.'
        }
        Write-Output 'PASS Windows PowerShell 5.1 manifest file enumeration and byte counts'

        $path=Join-Path $Temporary 'shape.json'
        foreach($case in @(@{Json='[]';Count=0},@{Json='[{"name":"one"}]';Count=1},@{Json='[{"name":"one"},{"name":"two"}]';Count=2})){
            [IO.File]::WriteAllText($path,$case.Json)
            $items=@(Read-Json $path)
            Assert ($items.Count -eq $case.Count) 'JSON array cardinality changed.'
        }
        [IO.File]::WriteAllText($path,'{"Models":["9b-q4","9b-q6"],"Profiles":{"9b-q4":{"Mode":"serial"}}}')
        $config=Read-Json $path
        Assert ($config.Models.Count -eq 2 -and $config.Profiles.'9b-q4'.Mode -eq 'serial') 'Nested configuration changed.'
        Write-Output 'PASS Empty/single/multiple arrays and nested configuration retain their shape'

        # Only Whisper is present. A pyannote result must not inherit its state.
        function script:Find-ModelFile([string[]]$Roots,$File,[switch]$Full){
            Assert ($File -isnot [array]) 'Inventory received multiple files as one object.'
            if($File.path.StartsWith('whisper/')){return 'present'}
            return $null
        }
        $inventory=@(Get-Inventory $Root @($Temporary))
        Assert (($inventory|Where-Object {$_.Id -eq 'whisper'}).State -like 'gefunden*') 'Whisper inventory is incorrect.'
        Assert (($inventory|Where-Object {$_.Id -eq 'pyannote'}).State -eq 'fehlt') 'Missing pyannote must remain missing.'
        Write-Output 'PASS Startup inventory evaluates audio files separately'
    } $root $temporary
} finally {Remove-Item -LiteralPath $temporary -Recurse -Force;Remove-Module $module}
Write-Output 'All 4 Windows PowerShell 5.1 JSON compatibility cases passed (simulated cmdlet output).'
