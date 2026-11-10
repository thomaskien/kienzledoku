$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$cases=@(
    @{Name='version';Arguments=@('--version')},
    @{Name='install';Arguments=@('--install','--no-distribution','--web-download')},
    @{Name='list';Arguments=@('--list','--running','--quiet')},
    @{Name='import';Arguments=@('--import','kienzledoku-server','C:\Users\Test User\Server\wsl','C:\Cache Files\ubuntu.wsl','--version','2')},
    @{Name='exec';Arguments=@('--distribution','kienzledoku-server','--user','root','--exec','python3','/mnt/c/Cache Files/test.py')},
    @{Name='shutdown';Arguments=@('--shutdown')},
    @{Name='terminate';Arguments=@('--terminate','kienzledoku-server')}
)
$records=@(foreach($case in $cases){
    $old=@(foreach($argument in $case.Arguments){'"'+[regex]::Replace([regex]::Replace($argument,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'}) -join ' '
    [pscustomobject]@{Name=$case.Name;Arguments=$case.Arguments;Raw=(ConvertTo-NativeArguments $case.Arguments);PreviousRaw=$old}
})
$records|ConvertTo-Json -Depth 8 -Compress
