param([switch]$RequireWindows)
$ErrorActionPreference='Stop'
if($env:OS -ne 'Windows_NT'){
    if($RequireWindows){throw 'Real Windows file permissions required; this check cannot run on Linux.'}
    Write-Output 'SKIP Windows private-file regression: no Windows/NTFS runtime available.'
    exit 0
}
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Read-Access([string]$Path){
    $sections=[Security.AccessControl.AccessControlSections]::Access -bor [Security.AccessControl.AccessControlSections]::Owner -bor [Security.AccessControl.AccessControlSections]::Group
    if($PSVersionTable.PSEdition -eq 'Desktop'){return [IO.File]::GetAccessControl($Path,$sections)}
    return [IO.FileSystemAclExtensions]::GetAccessControl((New-Object IO.FileInfo($Path)),$sections)
}
$temporary=Join-Path $env:LOCALAPPDATA ('kienzledoku-acl-test-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
try{
    $current=[Security.Principal.WindowsIdentity]::GetCurrent()
    $admin=(New-Object Security.Principal.WindowsPrincipal($current)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Write-Output ('Windows private-file regression; PowerShell '+$PSVersionTable.PSVersion+'; elevated='+$admin)
    $allowed=@($current.User.Value,'S-1-5-18','S-1-5-32-544')|Select-Object -Unique
    foreach($name in @('pending-install.json','hf.token','client.token')){
        $path=Join-Path $temporary $name
        [IO.File]::WriteAllText($path,'synthetic test content')
        $before=Read-Access $path
        Set-PrivateFile $path
        Set-PrivateFile $path
        $after=Read-Access $path
        Assert ($before.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq $after.GetOwner([Security.Principal.SecurityIdentifier]).Value) 'File owner changed.'
        Assert ($before.GetGroup([Security.Principal.SecurityIdentifier]).Value -eq $after.GetGroup([Security.Principal.SecurityIdentifier]).Value) 'File group changed.'
        Assert $after.AreAccessRulesProtected 'Access inheritance remains enabled.'
        $rules=@($after.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
        Assert ($rules.Count -eq @($allowed).Count) 'Unexpected number of access entries.'
        foreach($rule in $rules){
            Assert ($rule.IdentityReference.Value -in $allowed -and -not $rule.IsInherited) 'Unexpected/inherited identity can access private file.'
            Assert ($rule.AccessControlType -eq 'Allow' -and $rule.FileSystemRights -eq 'FullControl') 'Expected full control missing.'
        }
        Assert ([IO.File]::ReadAllText($path) -eq 'synthetic test content') 'Content changed during ACL update.'
        [IO.File]::WriteAllText($path,'synthetic rewrite')
        Set-PrivateFile $path
        Write-Output ('PASS protected '+$name+', repeat/rewrite, owner/group/content preserved')
    }
    $config=Join-Path $temporary 'pending-install.json'
    Write-Json $config @{Version=(Get-InstallerVersion);Models=@('9b-q4')}
    Set-PrivateFile $config
    Assert ((Read-Json $config).Version -eq (Get-InstallerVersion)) 'Config replacement cannot be protected/read.'
    Write-Output 'PASS atomic config replacement can be secured and read again'
}finally{Remove-Item -LiteralPath $temporary -Recurse -Force}
Write-Output 'All 4 real Windows private-file cases passed.'
