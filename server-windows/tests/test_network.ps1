$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'windows/Core.psm1') -Force -DisableNameChecking
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'windows/Engine.ps1'),[ref]$tokens,[ref]$errors)
$definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Set-ServerNetwork'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$script:Passed=0
function Assert($Value,[string]$Message){if(-not $Value){throw $Message}}
function Case([string]$Name,[scriptblock]$Body){Reset;& $Body;$script:Passed++;Write-Output ('PASS '+$Name)}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('kienzledoku-network-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temporary)|Out-Null
function Reset {
    $script:Cfg=[pscustomobject]@{StateDirectory=$temporary;NetworkMode='lan';NetworkAddress='10.0.83.140';NetworkRemove=$false}
    $script:Firewall=$null;$script:Commands=@();$script:Admin=$true;$script:Busy=$false;$script:WrongActiveProfile=$false
    $script:Created=0;$script:Started=@();$script:Messages=@()
    Remove-Item -LiteralPath (Join-Path $temporary 'network-owned.json') -Force -ErrorAction SilentlyContinue
}
function Is-Admin {return $script:Admin}
function Log([string]$Message){$script:Messages+=$Message}
function Invoke-Native {param([string]$Exe,[string[]]$Arguments,[switch]$AllowFailure) $script:Commands+=,@($Arguments);if($AllowFailure){return 0}}
function Start-Service {param([string]$Name) $script:Started+=$Name}
function Get-NetIPAddress {param([string]$AddressFamily,[string]$IPAddress,[string]$ErrorAction) if($IPAddress -eq '10.0.83.140'){[pscustomobject]@{IPAddress=$IPAddress}}}
function Get-NetTCPConnection {param([int]$LocalPort,[string]$State,[string]$ErrorAction) if($script:Busy){[pscustomobject]@{LocalAddress='10.0.83.140'}}}
function Get-NetFirewallRule {
    param([string]$Name,[string]$PolicyStore,[string]$ErrorAction)
    if($PolicyStore -eq 'ActiveStore' -and $script:WrongActiveProfile){
        return [pscustomobject]@{Enabled='True';Profile='Private, Domain';Action='Allow'}
    }
    return $script:Firewall
}
function Remove-NetFirewallRule {param([Parameter(ValueFromPipeline=$true)]$InputObject) process{$script:Firewall=$null}}
function New-NetFirewallRule {
    param([string]$Name,[string]$DisplayName,[string]$Direction,[string]$Action,[string]$Enabled,
          [string]$Protocol,[int]$LocalPort,[string]$LocalAddress,[string]$RemoteAddress,[string[]]$Profile)
    $script:Created++
    $script:Firewall=[pscustomobject]@{Name=$Name;Direction=$Direction;Action=$Action;Enabled=$Enabled;
        Protocol=$Protocol;LocalPort=$LocalPort;LocalAddress=$LocalAddress;RemoteAddress=$RemoteAddress;Profile=($Profile -join ', ')}
    return $script:Firewall
}
function Set-NetConnectionProfile {throw 'Global network profile must not be changed.'}
function Assert-LimitedRule {
    Assert ($script:Firewall.Profile -eq 'Any' -and $script:Firewall.Enabled -eq 'True') 'Public profile not covered.'
    Assert ($script:Firewall.LocalAddress -eq '10.0.83.140' -and $script:Firewall.LocalPort -eq 8185) 'Selected endpoint widened.'
    Assert ($script:Firewall.RemoteAddress -eq 'LocalSubnet' -and $script:Firewall.Protocol -eq 'TCP') 'Client or protocol scope widened.'
}
try{
    Case 'LAN rule covers Public while retaining the selected address, port and subnet' {
        Set-ServerNetwork
        Assert-LimitedRule
        $add=@($script:Commands | Where-Object {$_[2] -eq 'add'})
        Assert ($add.Count -eq 1 -and ($add[0] -join ' ').Contains('connectaddress=127.0.0.1')) 'Loopback forwarding missing.'
        Assert ($script:Started -contains 'iphlpsvc') 'Forwarding service not started.'
    }
    Case 'Repair replaces the previous private-only rule and preserves its cleanup ownership' {
        $script:Firewall=[pscustomobject]@{Profile='Private, Domain'}
        Write-Json (Join-Path $temporary 'network-owned.json') @{Address='10.0.83.140';Port=8185}
        Set-ServerNetwork
        Assert-LimitedRule
        Assert ($script:Commands.Count -eq 2 -and $script:Commands[0][2] -eq 'delete' -and $script:Commands[1][2] -eq 'add') 'Repair did not replace forwarding.'
        Assert ((Read-Json (Join-Path $temporary 'network-owned.json')).FirewallProfile -eq 'Any') 'Ownership record missing.'
    }
    Case 'Switching back to localhost removes owned forwarding and creates no new rule' {
        Set-ServerNetwork
        $script:Cfg.NetworkMode='local';Set-ServerNetwork
        Assert ($null -eq $script:Firewall -and $script:Created -eq 1) 'Local mode created LAN exposure.'
        Assert (-not(Test-Path -LiteralPath (Join-Path $temporary 'network-owned.json'))) 'Stale ownership record.'
    }
    Case 'Removal cleans owned networking even when the saved mode is LAN' {
        Set-ServerNetwork
        $script:Cfg.NetworkRemove=$true;Set-ServerNetwork
        Assert ($null -eq $script:Firewall -and $script:Created -eq 1) 'Removal recreated a LAN rule.'
    }
    Case 'Non-admin attempt fails before any networking mutation' {
        $script:Admin=$false;$message=''
        try{Set-ServerNetwork}catch{$message=$_.Exception.Message}
        Assert ($message.Contains('Administratorrechte') -and $script:Commands.Count -eq 0 -and $script:Created -eq 0) 'Non-admin action reached mutation.'
    }
    Case 'Wildcard, loopback, IPv6 and an address absent from Windows are refused' {
        foreach($address in @('0.0.0.0','127.0.0.1','::1','10.0.83.99')){
            $script:Cfg.NetworkAddress=$address;$failed=$false
            try{Set-ServerNetwork}catch{$failed=$true}
            Assert ($failed -and $script:Created -eq 0) ('Invalid address accepted: '+$address)
        }
    }
    Case 'An occupied selected endpoint is not replaced' {
        $script:Busy=$true;$failed=$false
        try{Set-ServerNetwork}catch{$failed=$true}
        Assert ($failed -and $script:Commands.Count -eq 0 -and $script:Created -eq 0) 'Foreign listener was replaced.'
    }
    Case 'Readback of an active rule still excluding Public cannot report success' {
        $script:WrongActiveProfile=$true;$message=''
        try{Set-ServerNetwork}catch{$message=$_.Exception.Message}
        Assert ($message.Contains('Firewallregel') -and -not ($script:Messages -match 'Firewallregel aktiv')) 'Invalid active profile silently accepted.'
    }
    Write-Output "All $script:Passed network regression cases passed (Windows cmdlets simulated; no Windows firewall modified)."
}finally{Remove-Item -LiteralPath $temporary -Recurse -Force}
