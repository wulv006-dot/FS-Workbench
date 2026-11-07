$ErrorActionPreference = 'Stop'
$secretDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) '.secrets'
$secretFile = Join-Path $secretDirectory 'discord.env'
if (-not (Test-Path -LiteralPath $secretDirectory)) {
    New-Item -ItemType Directory -Path $secretDirectory | Out-Null
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$directoryAcl = New-Object System.Security.AccessControl.DirectorySecurity
$directoryAcl.SetOwner($identity)
$directoryAcl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$directoryAcl.AddAccessRule($rule)
Set-Acl -LiteralPath $secretDirectory -AclObject $directoryAcl
$secureToken = Read-Host 'Paste the NEW MMOEXP FC Assistant Bot Token (input hidden)' -AsSecureString
$buffer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($buffer).Trim()
    if ($plainToken.Length -lt 30 -or $plainToken -match '\s') {
        throw 'Invalid token format. No value was saved.'
    }
    [IO.File]::WriteAllText($secretFile, "FC_ENABLE_LIVE=1`nDISCORD_BOT_TOKEN=$plainToken`n", [Text.UTF8Encoding]::new($false))
    $fileAcl = New-Object System.Security.AccessControl.FileSecurity
    $fileAcl.SetOwner($identity)
    $fileAcl.SetAccessRuleProtection($true, $false)
    $fileAcl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')))
    Set-Acl -LiteralPath $secretFile -AclObject $fileAcl
    Write-Host 'Saved locally with access limited to your Windows account. Do not send the token in chat.'
} finally {
    $plainToken = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($buffer)
    $secureToken.Dispose()
}
