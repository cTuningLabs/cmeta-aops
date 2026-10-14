# Licensed under the Apache License, Version 2.0.
# See the COPYRIGHT and LICENSE files in the project root for details.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$namespace = 'root/CIMV2/Security/MicrosoftVolumeEncryption'
$timer = [Diagnostics.Stopwatch]::StartNew()
$result = @{time=(Get-Date).ToString('o'); unlocked=$false;
            user_sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value}

try {
    $config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
    $osVolume = Get-CimInstance -Namespace $namespace -ClassName Win32_EncryptableVolume -Filter "DriveLetter='$($config.os_drive)'"
    $protection = Invoke-CimMethod -InputObject $osVolume -MethodName GetProtectionStatus
    if ($protection.ReturnValue -ne 0 -or $protection.ProtectionStatus -ne 1) { throw 'OS BitLocker protection must be On' }
    $stream = [IO.File]::OpenRead($config.key_file)
    try { if ($stream.Length -eq 0) { throw 'Empty external-key file' } } finally { $stream.Dispose() }

    $volume = $null
    while ($timer.Elapsed.TotalSeconds -lt 180) {
        $volume = @(Get-CimInstance -Namespace $namespace -ClassName Win32_EncryptableVolume |
            Where-Object { $_.DeviceID -eq $config.device -and $_.PersistentVolumeID -eq $config.persistent_id })
        if ($volume.Count -eq 1) { break }
        Start-Sleep -Seconds 3
    }
    if ($volume.Count -ne 1 -or $volume[0].DriveLetter -ne $config.drive) { throw 'Expected data volume/drive did not appear within 180 seconds' }
    $volume = $volume[0]
    $lock = Invoke-CimMethod -InputObject $volume -MethodName GetLockStatus
    if ($lock.ReturnValue -ne 0) { throw 'Cannot read volume lock status' }
    $result.already_unlocked = $lock.LockStatus -eq 0
    if (-not $result.already_unlocked) {
        Unlock-BitLocker -MountPoint $config.drive -RecoveryKeyPath $config.key_file | Out-Null
        $lock = Invoke-CimMethod -InputObject $volume -MethodName GetLockStatus
        if ($lock.ReturnValue -ne 0 -or $lock.LockStatus -ne 0) { throw 'Data volume did not unlock' }
    }
    $result.unlocked = $true
    $result.device = $config.device
    $result.drive = $config.drive
    $result.boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')
    $result.home_accessible = [bool]$config.home -and (Test-Path -LiteralPath $config.home)
} catch {
    $result.error = $_.Exception.Message
}

[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'last-run.json'), ($result | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
if (-not $result.unlocked) { Write-Error ('cMeta notice: ' + $result.error); exit 1 }
exit 0
