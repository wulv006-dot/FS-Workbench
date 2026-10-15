$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Connect-Hermes.ps1'),[ref]$tokens,[ref]$errors)
if($errors){throw $errors}
# Load real helper functions without opening the client or using real credentials.
foreach($function in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
    . ([scriptblock]::Create($function.Extent.Text))
}
$identity='/fixture/encrypted identity';$forward='127.0.0.1:19442:127.0.0.1:8942';$destination='fixture@server';$port=19442
$script:sessionToken='fixture-only'
$own=[pscustomobject]@{Name='ssh.exe';CommandLine="ssh -i `"$identity`" -L $forward $destination"}
if(-not (Test-HermesTunnelOwner $own)){throw 'Dedicated tunnel was not recognized'}
foreach($foreign in @($null,[pscustomobject]@{Name='other.exe';CommandLine=$own.CommandLine},[pscustomobject]@{Name='ssh.exe';CommandLine='ssh another-connection'},[pscustomobject]@{Name='ssh.exe';CommandLine=$null})){
    if(Test-HermesTunnelOwner $foreign){throw 'Foreign process was accepted'}
}
$script:calls=@();$script:rejectCredential=$false
function Invoke-RestMethod($Uri,$Headers,$TimeoutSec){
    $script:calls+= $Uri
    if($Headers['X-Hermes-Session-Token'] -ne 'fixture-only'){throw 'Missing credential'}
    if($Uri -match '/api/sessions' -and $script:rejectCredential){throw '401'}
    return [pscustomobject]@{gateway_running=$false}
}
if(-not (Test-HermesConnection)){throw 'Optional stopped messaging gateway blocked chat connection'}
if($script:calls.Count -ne 2 -or $script:calls[1] -notmatch 'sessions\?limit=0$'){throw 'Authenticated probe did not run'}
$script:rejectCredential=$true
if(Test-HermesConnection){throw 'Rejected credential was treated as connected'}
function Invoke-RestMethod {throw 'offline'}
if(Test-HermesConnection){throw 'Offline server was treated as connected'}
'PASS: syntax, dedicated/foreign process ownership, authenticated readiness, optional gateway, rejected credential, offline server'
