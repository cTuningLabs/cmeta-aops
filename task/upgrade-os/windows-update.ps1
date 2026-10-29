<#
upgrade-os: Windows Update through the PSWindowsUpdate module, software updates only (Microsoft Update also offers
every driver that matches the hardware, and -AcceptAll would install them all).

    windows-update.ps1 -Check      list the software updates
    windows-update.ps1             install them, without a reboot

Windows Update refuses an install to a remote logon, and an ssh session is one ("Access is denied", 0x80070005,
seen 2026-10-29; the search works): the install runs as SYSTEM in a scheduled task of its own, which this
script registers, starts, waits for, prints the log of and removes. -AsSystem is that inner run. Registering a
task for SYSTEM needs an elevated shell, as Windows Update itself does.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
#>

param([switch]$Check, [switch]$AsSystem, [string]$Log)

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

function Use-PSWindowsUpdate {
    # Never a question nobody can answer: TLS 1.2 and the NuGet provider come before Install-Module - the stock
    # PowerShellGet 1.0.0.1 asks whether to install NuGet, and a run over ssh waited for that answer for good
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    if (-not (Get-Module -ListAvailable PSWindowsUpdate)) {
        $scope = if ($AsSystem) { 'AllUsers' } else { 'CurrentUser' }
        if (-not (Get-PackageProvider -ListAvailable -Name NuGet -ErrorAction SilentlyContinue)) {
            Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope $scope | Out-Null
        }
        Install-Module PSWindowsUpdate -Force -Scope $scope -Confirm:$false
    }
    Import-Module PSWindowsUpdate
}

# The list: a search works from any session
if ($Check) {
    Use-PSWindowsUpdate
    Get-WindowsUpdate -UpdateType Software
    exit 0
}

# The inner run, as SYSTEM: everything it says goes into the log that the outer run prints
if ($AsSystem) {
    try {
        Use-PSWindowsUpdate
        $out = Get-WindowsUpdate -UpdateType Software -AcceptAll -Install -IgnoreReboot *>&1
        $out | Out-String -Width 200 | Out-File -LiteralPath $Log -Encoding utf8
        # an update that did not install fails the step
        if ($out | Where-Object { $_.Result -eq 'Failed' }) { exit 1 }
        exit 0
    } catch {
        "windows-update: $($_.Exception.Message)" | Out-File -LiteralPath $Log -Encoding utf8 -Append
        exit 1
    }
}

# The outer run: a task of its own for SYSTEM (on battery too), started now, waited for, its log printed, removed
$name = 'cmeta-upgrade-os-windows-update-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$Log = Join-Path ([IO.Path]::GetTempPath()) "$name.log"
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -AsSystem -Log "{1}"' -f $PSCommandPath, $Log

try {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
    $principal = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
} catch {
    [Console]::Error.WriteLine("windows-update: cannot register a task for SYSTEM (an elevated shell is needed): $($_.Exception.Message)")
    exit 1
}

"windows-update: installing as SYSTEM through the scheduled task $name (Windows Update installs nothing for a remote session); its log follows when it ends"
[Console]::Out.Flush()

try {
    Start-ScheduledTask -TaskName $name
    do {
        Start-Sleep -Seconds 5
        $state = (Get-ScheduledTask -TaskName $name).State
    } while ($state -eq 'Running' -or $state -eq 'Queued')
    $rc = (Get-ScheduledTaskInfo -TaskName $name).LastTaskResult
    if (Test-Path -LiteralPath $Log) {
        Get-Content -LiteralPath $Log -Encoding utf8
    } else {
        [Console]::Error.WriteLine("windows-update: the task left no log (its result: $rc)")
        if (-not $rc) { $rc = 1 }
    }
} finally {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Log -ErrorAction SilentlyContinue
}

exit $rc
