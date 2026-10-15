$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$access=Join-Path $workspace '.agent_runtime/hermes-desktop-20261015/access'
$identity=Join-Path $access 'identity'
$token=Join-Path $access 'token'
$known=Join-Path $workspace 'server_187/access/known_hosts'
$desktop=Join-Path $env:LOCALAPPDATA 'hermes/hermes-agent/apps/desktop/release/win-unpacked/Hermes.exe'
foreach($path in @($identity,$token,$known,$desktop)){if(-not(Test-Path -LiteralPath $path)){throw "Missing connection file: $path"}}
if((Get-Service ssh-agent).Status -ne 'Running'){Start-Service ssh-agent}
$port=19442
$connection=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if(-not $connection){
    $arguments=@('-N','-T','-i',('"'+$identity+'"'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',('UserKnownHostsFile="'+$known+'"'),'-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3','-L',"127.0.0.1:${port}:127.0.0.1:8942",'fs-hermes-desktop@47.85.224.112')
    $tunnel=Start-Process ssh.exe -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $access 'tunnel-error.log')
    [IO.File]::WriteAllText((Join-Path $access 'tunnel-pid'),[string]$tunnel.Id)
}
$env:HERMES_DESKTOP_REMOTE_URL="http://127.0.0.1:$port"
$env:HERMES_DESKTOP_REMOTE_TOKEN=[IO.File]::ReadAllText($token).Trim()
$env:HERMES_DESKTOP_USER_DATA_DIR=Join-Path $access 'desktop-state'
$env:HERMES_HOME=Join-Path $access 'client-home'
$ready=$false
for($attempt=0;$attempt -lt 30;$attempt++){
    try{
        $response=Invoke-WebRequest "$env:HERMES_DESKTOP_REMOTE_URL/api/health" -Headers @{'X-Hermes-Session-Token'=$env:HERMES_DESKTOP_REMOTE_TOKEN} -TimeoutSec 2
        if($response.StatusCode -eq 200){$ready=$true;break}
    }catch{Start-Sleep -Milliseconds 500}
}
if(-not $ready){throw 'Hermes server connection failed; inspect the dedicated tunnel log.'}
Start-Process -FilePath $desktop
Remove-Item Env:HERMES_DESKTOP_REMOTE_TOKEN
Write-Output 'Hermes智体已打开；会话与业务约定保存在服务器。'
