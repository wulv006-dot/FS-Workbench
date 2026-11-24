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
$null = New-Item -ItemType Directory -Force -Path $folder
$build = Join-Path $folder ('tray-' + [guid]::NewGuid() + '.exe')
try {
    & $compiler /nologo /codepage:65001 /optimize+ /target:winexe "/out:$build" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll /r:System.Net.Http.dll $source
    if ($LASTEXITCODE -ne 0) { throw 'Failed to compile the Windows tray viewer.' }
    if ($existing -and $existing.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $taskName
        for ($i = 0; $i -lt 40 -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Running'; $i++) {
            Start-Sleep -Milliseconds 250
        }
    }
    if (Test-Path -LiteralPath $program) {
        [IO.File]::Replace($build,$program,[System.Management.Automation.Language.NullString]::Value)
    } else {
        [IO.File]::Move($build,$program)
    }
    $action = New-ScheduledTaskAction -Execute $program -WorkingDirectory $folder
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Output "$taskName  $program"
} finally {
    if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build }
}
