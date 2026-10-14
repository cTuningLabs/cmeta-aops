# Licensed under the Apache License, Version 2.0.
# See the COPYRIGHT and LICENSE files in the project root for details.

param([Parameter(Mandatory=$true)][string]$Data)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$config = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Data)) | ConvertFrom-Json
$settings = $config.settings
$options = $config.options
$selected = $config.selected
$namespace = 'root/CIMV2/Security/MicrosoftVolumeEncryption'

function Native([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

function Protect-Directory([string]$Path, [bool]$ReadExecutables=$false) {
    if (Test-Path -LiteralPath $Path) { throw "Directory already exists: $Path; inspect it before provisioning" }
    New-Item -ItemType Directory -Path $Path | Out-Null
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $sddl = 'O:BAG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    if ($ReadExecutables) { $sddl += '(A;OICI;0x1200a9;;;AU)' }
    $acl.SetSecurityDescriptorSddlForm($sddl)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Read-State {
    $services = @{}
    foreach ($name in @($settings.ssh_service, $settings.tailscale_service)) {
        $service = Get-CimInstance Win32_Service -Filter "Name='$name'"
        $services[$name] = if ($service) {
            @{state=$service.State; start=$service.StartMode; path=$service.PathName; account=$service.StartName}
        } else { @{state='missing'} }
    }
    $volumes = @()
    $volumeError = $null
    try {
        $volumes = @(Get-CimInstance -Namespace $namespace -ClassName Win32_EncryptableVolume |
            ForEach-Object {
                $lock = Invoke-CimMethod -InputObject $_ -MethodName GetLockStatus
                $protection = Invoke-CimMethod -InputObject $_ -MethodName GetProtectionStatus
                $external = Invoke-CimMethod -InputObject $_ -MethodName GetKeyProtectors -Arguments @{KeyProtectorType=[uint32]2}
                @{drive=$_.DriveLetter; device=$_.DeviceID; persistent_id=$_.PersistentVolumeID;
                  lock=$lock.LockStatus; protection=$protection.ProtectionStatus; type=$_.VolumeType;
                  external_protector_ids=$external.VolumeKeyProtectorID}
            })
    } catch { $volumeError = 'BitLocker inventory unavailable; elevated Windows Pro/Enterprise may be required.' }
    $power = (& powercfg.exe /query SCHEME_CURRENT SUB_SLEEP 2>&1 | Out-String).Trim()
    $boot = @{}
    try {
        $task = Get-ScheduledTask -TaskName $settings.unlock_task -ErrorAction SilentlyContinue
        if ($task) {
            $info = Get-ScheduledTaskInfo -TaskName $settings.unlock_task
            $boot = @{task=$task.TaskName; state=[string]$task.State; last_result=$info.LastTaskResult}
        }
    } catch { $boot.note = 'Scheduled-task inventory unavailable' }
    $tail = @{}
    $cli = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $cli) {
        try {
            $status = (& $cli status --json 2>$null) | ConvertFrom-Json
            $tail.state = $status.BackendState
            $tail.addresses = $status.TailscaleIPs
            # Never return debug prefs: its Config includes private credentials.
            $prefs = (& $cli debug prefs 2>$null) | ConvertFrom-Json
            $tail.unattended = [bool]$prefs.ForceDaemon
        } catch { $tail.note = 'Tailscale status/preferences unavailable' }
    }
    return @{services=$services; volumes=$volumes; bitlocker_note=$volumeError; power=$power;
             tailscale=$tail; boot_unlock=$boot;
             home=$config.home; home_accessible=([bool]$config.home -and (Test-Path -LiteralPath $config.home))}
}

try {
    if ($config.action -eq 'check') {
        Write-Output ('CMETA_RESULT=' + ((Read-State) | ConvertTo-Json -Depth 8 -Compress))
        exit 0
    }
    if ($config.action -ne 'apply') { throw 'Unknown action' }
    $admin = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Apply requires an elevated Windows terminal; run the selected command as administrator.'
    }

    # Validate all selected prerequisites before changing any service.
    $ssh = Get-CimInstance Win32_Service -Filter "Name='$($settings.ssh_service)'"
    $newSsh = $selected.ssh -and -not $ssh
    $source = $null
    $destination = Join-Path ($env:SystemDrive + '\') $settings.ssh_directory
    $sshData = Join-Path $env:ProgramData 'ssh'
    $sshConfig = Join-Path $sshData 'sshd_config'
    $keyLines = @()
    if ($selected.ssh) {
        if ($options.sshd_source) {
            $source = [IO.Path]::GetFullPath($options.sshd_source)
            if (-not (Test-Path -LiteralPath (Join-Path $source 'sshd.exe'))) { throw '--sshd_source must contain the complete portable OpenSSH package' }
            if ($ssh -and $ssh.PathName -match '\s-[A-Za-z]') { throw 'Custom sshd service arguments require manual relocation; existing configuration was preserved.' }
            if (Test-Path -LiteralPath $destination) { throw 'Managed SSH destination already exists; inspect it rather than replacing binaries.' }
            if (-not (Test-Path -LiteralPath (Join-Path $source 'ssh-keygen.exe'))) { throw 'Portable package ssh-keygen missing' }
        } elseif ($ssh -and $ssh.PathName -notmatch ('^"?' + [regex]::Escape($env:SystemDrive + '\'))) {
            throw 'sshd is outside the OS drive. Supply --sshd_source=<complete package directory> to relocate it for next boot.'
        }
        if ($newSsh) {
            if (-not $source) { throw 'A new SSH service requires the complete portable package from cMeta tool setup.' }
            if (Test-Path -LiteralPath $sshConfig) { throw 'Existing sshd_config without a service: inspect/install it manually to preserve configuration.' }
            if (-not $options.keys -or -not (Test-Path -LiteralPath $options.keys -PathType Leaf)) {
                throw 'A new Windows SSH service requires --keys=<public-key file> for administrator access.'
            }
            $keyLines = @(Get-Content -LiteralPath $options.keys | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') })
            if (-not $keyLines.Count -or @($keyLines | Where-Object { $_ -notmatch '^(ssh-|ecdsa-|sk-)\S+\s+[A-Za-z0-9+/]+={0,3}(\s.*)?$' }).Count) {
                throw 'Invalid public-key file; never supply a private key.'
            }
            if (Get-NetFirewallRule -Name $settings.firewall_name -ErrorAction SilentlyContinue) {
                throw 'Firewall rule name already exists; inspect it before installing SSH.'
            }
        }
    }

    $tailscale = $null
    if ($selected.tailscale) {
        if (-not (Get-Service -Name $settings.tailscale_service -ErrorAction SilentlyContinue)) { throw 'Install and authenticate Tailscale first, then rerun setup.' }
        $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
        if (-not $tailscale) { $tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe' }
        if (-not (Test-Path -LiteralPath $tailscale)) { throw 'Tailscale CLI missing' }
        $statusText = & $tailscale status --json
        if ($LASTEXITCODE -ne 0) { throw 'Tailscale status failed; authenticate it locally first.' }
        $status = $statusText | ConvertFrom-Json
        if ($status.BackendState -ne 'Running') { throw 'Tailscale must already be authenticated and Running.' }
    }

    $unlockRoot = Join-Path ($env:SystemDrive + '\') $settings.unlock_directory
    if ($selected.boot_unlock) {
        $osVolume = Get-BitLockerVolume -MountPoint $env:SystemDrive
        if ($osVolume.EncryptionPercentage -ne 100 -or $osVolume.ProtectionStatus.ToString() -ne 'On') {
            throw 'OS volume must be 100% encrypted with protection On. UsedSpaceOnlyEncrypted is accepted.'
        }
        $device = '\\?\Volume{' + $options.volume_guid + '}\'
        $persistent = '{' + $options.persistent_id + '}'
        $volume = @(Get-CimInstance -Namespace $namespace -ClassName Win32_EncryptableVolume |
            Where-Object { $_.DeviceID -eq $device -and $_.PersistentVolumeID -eq $persistent })
        if ($volume.Count -ne 1 -or $volume[0].DriveLetter -ne $options.drive) { throw 'Data volume GUID, persistent ID and expected drive letter must all match.' }
        $volume = $volume[0]
        $dataVolume = Get-BitLockerVolume -MountPoint $options.drive
        if ($dataVolume.LockStatus.ToString() -ne 'Unlocked') { throw 'Unlock the intended data volume locally before provisioning.' }
        $protector = '{' + $options.protector_id + '}'
        if (-not @($dataVolume.KeyProtector | Where-Object {
            $_.KeyProtectorId -eq $protector -and $_.KeyProtectorType.ToString() -eq 'ExternalKey'
        }).Count) { throw 'The selected protector must be an existing ExternalKey protector.' }
        if ((Test-Path -LiteralPath $unlockRoot) -or (Get-ScheduledTask -TaskName $settings.unlock_task -ErrorAction SilentlyContinue)) {
            throw 'Boot unlock already provisioned. Inspect its identity, ACL and task; no key or task was replaced.'
        }
        if (-not (Test-Path -LiteralPath $config.helper)) { throw 'Boot unlock helper missing' }
    }

    if ($selected.ssh) {
        if ($source) {
            # Copy the entire package; sshd launches sibling binaries. Never remove the original.
            Protect-Directory $destination $true
            Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $destination -Recurse
            foreach ($file in Get-ChildItem -LiteralPath $source -Recurse -File -Force) {
                $relative = $file.FullName.Substring($source.TrimEnd('\').Length).TrimStart('\')
                if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath (Join-Path $destination $relative)).Hash) { throw 'SSH package copy hash mismatch' }
            }
            if ($ssh) {
                $changed = Invoke-CimMethod -InputObject $ssh -MethodName Change -Arguments @{PathName=('"' + (Join-Path $destination 'sshd.exe') + '"')}
                if ($changed.ReturnValue -ne 0) { throw 'Could not change sshd binary path; original package retained.' }
                Write-Output 'cMeta info: Existing running sshd kept; the relocated binary will be used on next service start.'
            } else {
                # Create only sshd. The upstream installer also deletes/recreates ssh-agent.
                New-Service -Name $settings.ssh_service -DisplayName 'OpenSSH SSH Server' -BinaryPathName ('"' + (Join-Path $destination 'sshd.exe') + '"') -StartupType Manual | Out-Null
                Native sc.exe @('privs', $settings.ssh_service, 'SeAssignPrimaryTokenPrivilege/SeTcbPrivilege/SeBackupPrivilege/SeRestorePrivilege/SeImpersonatePrivilege')
            }
        }
        if ($newSsh) {
            if (-not (Test-Path -LiteralPath $sshData)) { New-Item -ItemType Directory -Path $sshData | Out-Null }
            $contents = @(
                "Port $($options.port)", 'AddressFamily inet', 'PubkeyAuthentication yes',
                'PasswordAuthentication no', 'KbdInteractiveAuthentication no',
                'AuthorizedKeysFile .ssh/authorized_keys', 'Subsystem sftp sftp-server.exe',
                'Match Group administrators', '    AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys'
            ) -join "`r`n"
            [IO.File]::WriteAllText($sshConfig, $contents + "`r`n", (New-Object Text.UTF8Encoding($false)))
            $authorized = Join-Path $sshData 'administrators_authorized_keys'
            $existing = if (Test-Path -LiteralPath $authorized) { @(Get-Content -LiteralPath $authorized) } else { @() }
            [IO.File]::WriteAllLines($authorized, @($existing + $keyLines | Select-Object -Unique), (New-Object Text.UTF8Encoding($false)))
            foreach ($file in @($sshConfig, $authorized)) {
                $acl = New-Object Security.AccessControl.FileSecurity
                $acl.SetSecurityDescriptorSddlForm('O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)')
                Set-Acl -LiteralPath $file -AclObject $acl
            }
            New-NetFirewallRule -Name $settings.firewall_name -DisplayName 'cMeta SSH setup' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $options.port -RemoteAddress $options.remote_address | Out-Null
            $binary = if ($source) { Join-Path $destination 'sshd.exe' } else { Join-Path $env:SystemRoot 'System32\OpenSSH\sshd.exe' }
            Native (Join-Path (Split-Path $binary) 'ssh-keygen.exe') @('-A')
            Native $binary @('-t')
        }
        Set-Service -Name $settings.ssh_service -StartupType Automatic
        Native sc.exe @('failure', $settings.ssh_service, 'reset=', '86400', 'actions=', 'restart/60000/restart/60000/restart/60000')
        Start-Service -Name $settings.ssh_service
    }

    if ($selected.tailscale) {
        Set-Service -Name $settings.tailscale_service -StartupType Automatic
        Start-Service -Name $settings.tailscale_service
        Native $tailscale @('set', '--unattended=true')
    }
    if ($selected.keep_awake) {
        Native powercfg.exe @('/change', 'standby-timeout-ac', '0')
        Native powercfg.exe @('/change', 'hibernate-timeout-ac', '0')
    }

    if ($selected.boot_unlock) {
        $beforeIds = @($dataVolume.KeyProtector | ForEach-Object KeyProtectorId | Sort-Object)
        Protect-Directory $unlockRoot
        $saved = Invoke-CimMethod -InputObject $volume -MethodName SaveExternalKeyToFile -Arguments @{VolumeKeyProtectorID=$protector; Path=$unlockRoot}
        if ($saved.ReturnValue -ne 0) { throw 'Could not save existing external key on the protected OS volume' }
        $name = Invoke-CimMethod -InputObject $volume -MethodName GetExternalKeyFileName -Arguments @{VolumeKeyProtectorID=$protector}
        if ($name.ReturnValue -ne 0 -or -not $name.FileName -or [IO.Path]::GetFileName($name.FileName) -ne $name.FileName) { throw 'Invalid external-key filename' }
        $keyFile = Join-Path $unlockRoot $name.FileName
        if (-not (Test-Path -LiteralPath $keyFile)) { throw 'External key was not exported' }
        $helper = Join-Path $unlockRoot 'unlock-data.ps1'
        Copy-Item -LiteralPath $config.helper -Destination $helper
        $bootConfig = @{device=$device; persistent_id=$persistent; drive=$options.drive; key_file=$keyFile;
                        os_drive=$env:SystemDrive; home=$config.home}
        [IO.File]::WriteAllText((Join-Path $unlockRoot 'config.json'), ($bootConfig | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
        foreach ($file in Get-ChildItem -LiteralPath $unlockRoot -File -Force) {
            $acl = New-Object Security.AccessControl.FileSecurity
            $acl.SetSecurityDescriptorSddlForm('O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)')
            Set-Acl -LiteralPath $file.FullName -AclObject $acl
        }
        $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $helper + '"')
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = 'PT15S'
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)
        $afterIds = @((Get-BitLockerVolume -MountPoint $options.drive).KeyProtector | ForEach-Object KeyProtectorId | Sort-Object)
        if (@(Compare-Object $beforeIds $afterIds).Count) { throw 'Protector identities changed unexpectedly' }
        Register-ScheduledTask -TaskName $settings.unlock_task -Action $action -Trigger $trigger -Principal $principal -Settings $taskSettings -Description 'Unlock the explicitly identified cMeta data volume before login; existing protectors retained.' | Out-Null
        Start-ScheduledTask -TaskName $settings.unlock_task
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $record = Join-Path $unlockRoot 'last-run.json'
        while (-not (Test-Path -LiteralPath $record) -and $timer.Elapsed.TotalSeconds -lt 30) { Start-Sleep -Seconds 1 }
        if (-not (Test-Path -LiteralPath $record)) { throw 'Boot unlock task installed, but its SYSTEM verification did not finish within 30 seconds. Inspect the task before rebooting.' }
        $verified = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
        if (-not $verified.unlocked -or $verified.user_sid -ne 'S-1-5-18') { throw 'Boot unlock task installed, but SYSTEM verification failed. Inspect last-run.json before rebooting.' }
    }
    Write-Output ('CMETA_RESULT=' + ((Read-State) | ConvertTo-Json -Depth 8 -Compress))
} catch {
    Write-Error ('cMeta notice: ' + $_.Exception.Message)
    exit 1
}
