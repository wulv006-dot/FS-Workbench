$ErrorActionPreference = 'Stop'
$taskName = 'FS-FC27-QuoteTray'
$folder = Join-Path $env:LOCALAPPDATA 'FS/fc27-quote-tray'
$program = Join-Path $folder 'FsQuoteTray.exe'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$source = Join-Path $PSScriptRoot 'QuoteTray.cs'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions[0].Execute -ne $program)) {
    throw 'An existing task with this name starts a different program.'
}
$wasRunning = $existing -and $existing.State -eq 'Running'
$previousDefinition = if ($existing) { Export-ScheduledTask -TaskName $taskName }
$null = New-Item -ItemType Directory -Force -Path $folder
$build = Join-Path $folder ('tray-' + [guid]::NewGuid() + '.exe')
$backup = $build + '.previous'
$replaced = $false
$stopped = $false
$registered = $false

function Stop-QuoteTray {
    $oldProcesses = @(Get-Process -Name FsQuoteTray -ErrorAction SilentlyContinue | Where-Object Path -EQ $program)
    Stop-ScheduledTask -TaskName $taskName
    foreach ($process in $oldProcesses) {
        if (-not $process.WaitForExit(10000)) { throw 'Previous tray instance is still running.' }
    }
    for ($i = 0; $i -lt 40 -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Running'; $i++) {
        Start-Sleep -Milliseconds 250
    }
    if ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') { throw 'Tray task is still running.' }
}

try {
    & $compiler /nologo /codepage:65001 /optimize+ /target:winexe "/out:$build" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll /r:System.Net.Http.dll $source
    if ($LASTEXITCODE -ne 0) { throw 'Failed to compile the Windows tray viewer.' }
    if ($wasRunning) {
        $stopped = $true
        Stop-QuoteTray
    }
    if (Test-Path -LiteralPath $program) {
        [IO.File]::Replace($build,$program,$backup)
    } else {
        [IO.File]::Move($build,$program)
    }
    $replaced = $true
    $action = New-ScheduledTaskAction -Execute $program -WorkingDirectory $folder
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $registered = $true
    Start-ScheduledTask -TaskName $taskName
    $started = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 250
        $instances = @(Get-Process -Name FsQuoteTray -ErrorAction SilentlyContinue | Where-Object Path -EQ $program)
        if ($instances.Count -eq 1 -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
            if (-not $instances[0].WaitForExit(1000)) { $started = $true; break }
        }
    }
    if (-not $started) { throw 'Tray task started but its windowless viewer did not stay running.' }
    [IO.File]::Delete($backup)
    Write-Output "$taskName  $program"
} catch {
    if ($registered -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Running') { Stop-QuoteTray }
    if ($replaced) {
        if ([IO.File]::Exists($backup)) {
            [IO.File]::Replace($backup,$program,[System.Management.Automation.Language.NullString]::Value)
        } else {
            [IO.File]::Delete($program)
        }
    }
    if ($registered) {
        if ($previousDefinition) {
            Register-ScheduledTask -TaskName $taskName -Xml $previousDefinition -Force | Out-Null
        } else {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
    }
    if ($stopped -and (Get-ScheduledTask -TaskName $taskName).State -ne 'Running') {
        Start-ScheduledTask -TaskName $taskName
    }
    throw
} finally {
    if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build }
}
