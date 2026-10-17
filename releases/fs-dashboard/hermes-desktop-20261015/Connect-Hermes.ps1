param([switch]$Watch)
$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$access=Join-Path $workspace '.agent_runtime/hermes-desktop-20261015/access'
$identity=Join-Path $access 'identity'
$token=Join-Path $access 'token'
$known=Join-Path $workspace 'server_187/access/known_hosts'
$desktop=Join-Path $env:LOCALAPPDATA 'hermes/hermes-agent/apps/desktop/release/win-unpacked/Hermes.exe'
$port=19442
$forward="127.0.0.1:${port}:127.0.0.1:8942"
$destination='fs-hermes-desktop@47.85.224.112'

function Test-HermesTunnelOwner($owner) {
    return ($null -ne $owner -and $owner.Name -eq 'ssh.exe' -and
        $null -ne $owner.CommandLine -and $owner.CommandLine.Contains($identity) -and
        $owner.CommandLine.Contains($forward) -and $owner.CommandLine.Contains($destination))
}

function Get-HermesTunnel {
    $listener=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if(-not $listener){return}
    $owner=Get-CimInstance Win32_Process -Filter ("ProcessId="+$listener[0].OwningProcess)
    if(-not (Test-HermesTunnelOwner $owner)){
        throw '连接端口被其他程序占用，请关闭占用程序后再试。'
    }
    return Get-Process -Id $owner.ProcessId -ErrorAction Stop
}

function Test-HermesConnection {
    try {
        $status=Invoke-RestMethod "http://127.0.0.1:$port/api/status" -Headers @{'X-Hermes-Session-Token'=$script:sessionToken} -TimeoutSec 3
        # Upstream status is public; sessions verifies the actual desktop credential.
        $null=Invoke-RestMethod "http://127.0.0.1:$port/api/sessions?limit=0" -Headers @{'X-Hermes-Session-Token'=$script:sessionToken} -TimeoutSec 3
        return ($null -ne $status.gateway_running)
    }catch{return $false}
}

function Start-HermesTunnel {
    $arguments=@('-N','-T','-i',('"'+$identity+'"'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',('UserKnownHostsFile="'+$known+'"'),'-o','ExitOnForwardFailure=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','-L',$forward,$destination)
    $process=Start-Process ssh.exe -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $access 'tunnel-error.log')
    [IO.File]::WriteAllText((Join-Path $access 'tunnel-pid'),[string]$process.Id)
    return $process
}

try {
    foreach($path in @($identity,$token,$known,$desktop)){if(-not(Test-Path -LiteralPath $path)){throw "缺少连接文件：$path"}}
    $script:sessionToken=[IO.File]::ReadAllText($token).Trim()
    if($Watch){
        $mutex=[Threading.Mutex]::new($false,'Local\HermesServer187Connection')
        if(-not $mutex.WaitOne(0)){ $mutex.Dispose(); exit }
        try {
            $failures=0
            $tunnel=$null
            while($true){
                try {
                    if((Get-Service ssh-agent).Status -ne 'Running'){Start-Service ssh-agent}
                    if($tunnel){$tunnel.Refresh()}
                    if(-not $tunnel -or $tunnel.HasExited){
                        $tunnel=Get-HermesTunnel
                        if(-not $tunnel){$tunnel=Start-HermesTunnel}
                        $failures=0
                    }
                    if(Test-HermesConnection){$failures=0}else{$failures++}
                    if($failures -ge 3){
                        # Recheck listener ownership before stopping the dedicated process.
                        $owner=Get-CimInstance Win32_Process -Filter ("ProcessId="+$tunnel.Id)
                        if(Test-HermesTunnelOwner $owner){$tunnel.Kill()}
                        $tunnel=$null
                    }
                }catch{
                    [IO.File]::WriteAllText((Join-Path $access 'connection-error.log'),"$(Get-Date -Format o) 连接暂不可用；五秒后自动重试。")
                }
                Start-Sleep -Seconds 5
            }
        }finally{$mutex.ReleaseMutex();$mutex.Dispose()}
    }
    $null=Get-HermesTunnel
    $null=Start-Process (Join-Path $PSHOME 'pwsh.exe') -WindowStyle Hidden -ArgumentList @('-NoProfile','-File',('"'+$PSCommandPath+'"'),'-Watch') -PassThru
    $ready=$false
    $startup=[Diagnostics.Stopwatch]::StartNew()
    while($startup.Elapsed.TotalSeconds -lt 45){
        if(Test-HermesConnection){$ready=$true;break}
        Start-Sleep -Seconds 1
    }
    if(-not $ready){throw '暂时无法连接服务器。连接程序会继续自动重试；网络恢复后请再次双击。详情见专用目录 tunnel-error.log。'}
    $env:HERMES_DESKTOP_REMOTE_URL="http://127.0.0.1:$port"
    $env:HERMES_DESKTOP_REMOTE_TOKEN=$script:sessionToken
    $env:HERMES_DESKTOP_USER_DATA_DIR=Join-Path $access 'desktop-state'
    $env:HERMES_HOME=Join-Path $access 'client-home'
    Start-Process -FilePath $desktop
}catch{
    if($Watch){throw}
    Add-Type -AssemblyName PresentationFramework
    $null=[System.Windows.MessageBox]::Show($_.Exception.Message,'Hermes智体连接提示','OK','Warning')
    throw
}finally{Remove-Item Env:HERMES_DESKTOP_REMOTE_TOKEN -ErrorAction SilentlyContinue}
