# Read-only probe of a Windows host: the same "key=value" and "repo|..." lines as probe.sh, for
# host/api/v1.py::probe. Runs locally (powershell -File) or over a Windows OpenSSH server (its text
# arrives as base64 lines on stdin and is run as one script - see _cmd_stdin).

$ErrorActionPreference = 'SilentlyContinue'

function Line($k, $v) { Write-Output ("{0}={1}" -f $k, ($v -join ' ').Trim()) }

# The machine and its OS
Line 'hostname' $env:COMPUTERNAME

$os = Get-CimInstance Win32_OperatingSystem
Line 'os' ("{0} {1}" -f $os.Caption, $os.Version)
Line 'kernel' ("Windows " + [Environment]::OSVersion.Version)
Line 'arch' $env:PROCESSOR_ARCHITECTURE
Line 'uptime' ("up since " + $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm'))

# The login
Line 'user' $env:USERNAME
Line 'home' $env:USERPROFILE

# Windows has no sudo: what matters is whether this session holds an elevated (Administrator) token.
# IsInRole is true only for an elevated token - an admin user under UAC without elevation gets false.
# An OpenSSH login of a member of Administrators is elevated; "sudo for Windows" (11 24H2+) is optional.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) { Line 'sudo' 'elevated' } else { Line 'sudo' 'not elevated' }
if (Get-Command sudo -ErrorAction SilentlyContinue) { Line 'windows_sudo' 'available' }

# The basic tools
Line 'python' ((& python --version 2>&1) | Select-Object -First 1)
Line 'uv' ((& uv --version 2>&1) | Select-Object -First 1)
Line 'git' ((& git --version 2>&1) | Select-Object -First 1)

# Container engines: the client version, and whether the Docker daemon answers ("(daemon down)" when the
# client is there but Docker Desktop is not running); "-" when not installed
if (Get-Command docker -ErrorAction SilentlyContinue) {
  $dv = (((& docker --version 2>&1) | Select-Object -First 1) -replace '^Docker version ', '') -replace ',.*$', ''
  $info = & docker info --format '{{.ServerVersion}}' 2>$null
  if ($LASTEXITCODE -eq 0 -and $info) { Line 'docker' $dv } else { Line 'docker' ($dv + ' (daemon down)') }
} else { Line 'docker' '-' }

if (Get-Command podman -ErrorAction SilentlyContinue) {
  Line 'podman' (((& podman --version 2>&1) | Select-Object -First 1) -replace '^podman version ', '')
} else { Line 'podman' '-' }

# cMeta: its command, its version and its home, as cMeta itself reports them ("cx --version")
$cx = (Get-Command cx -ErrorAction SilentlyContinue).Source
Line 'cx' $cx

$home_ = ''
if ($cx) {
  $v = & cx --version 2>$null
  $ver = ($v | Where-Object { $_ -match 'cMeta version' } | Select-Object -First 1) -replace '.*version\s*', ''
  Line 'cmeta_version' $ver

  # The home: "cx --print-home" (a cMeta newer than 0.35.1); an older cMeta has no such flag and fails, and its home is the
  # "cMeta home path" line of "cx --version"
  $printed = @(& cx --print-home 2>$null)
  if ($LASTEXITCODE -eq 0 -and $printed.Count -gt 0) { $home_ = "$($printed[-1])".Trim() }

  # only the label goes: ".*:" would also eat the drive letter of C:\Users\...
  if (-not $home_) { $home_ = (($v | Where-Object { $_ -match 'cMeta home path' } | Select-Object -First 1) -replace '^[^:]*:\s*', '') }
  Line 'cmeta_home' $home_
}

# Without cx there is nobody to ask for the home: the variable, else the default folder
if (-not $home_) { if ($env:CMETA_HOME) { $home_ = $env:CMETA_HOME } else { $home_ = Join-Path $env:USERPROFILE 'CMETA' } }

# The disk of the user's folder, the GPU, the processors
$drive = Get-PSDrive -Name ($env:USERPROFILE.Substring(0,1))

# plain integers: "{0:N0}" would group the thousands with the locale's separator (a no-break space in French)
if ($drive) { Line 'disk' ("{0} GB free of {1} GB" -f [math]::Round($drive.Free/1GB), [math]::Round(($drive.Used+$drive.Free)/1GB)) }

$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) { Line 'gpu' ((& nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>$null) | Select-Object -First 1) }

Line 'cpus' $env:NUMBER_OF_PROCESSORS

# The registered repositories: every path cx knows ("cx repo find", plugged ones included), else the
# folders under <cMeta home>\repos. Per repository: git branch/commit/date/changed files or "copy", the
# _cmr.yaml version and artifact (alias,UID - how the AOPS repository is recognised whatever its folder is called).
$list = @()
if ($cx) { $list = @(& cx repo find 2>$null | ForEach-Object { "$_".Trim() } | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }) }

$repos = Join-Path $home_ 'repos'
if ($list.Count -eq 0 -and (Test-Path -LiteralPath $repos)) { $list = @(Get-ChildItem -LiteralPath $repos -Directory | ForEach-Object { $_.FullName }) }

foreach ($p in $list) {
  $d = Get-Item -LiteralPath $p
  if (-not $d) { continue }

  # The version and the artifact of its descriptor
  $v = ''; $a = ''
  $cmr = Join-Path $d.FullName '_cmr.yaml'
  if (Test-Path -LiteralPath $cmr) {
    $m = Select-String -LiteralPath $cmr -Pattern '^version:\s*(.*)$' | Select-Object -First 1; if ($m) { $v = $m.Matches[0].Groups[1].Value.Trim(" `"'") }
    $m = Select-String -LiteralPath $cmr -Pattern '^artifact:\s*(.*)$' | Select-Object -First 1; if ($m) { $a = $m.Matches[0].Groups[1].Value.Trim(" `"'") }
  }

  # A git clone (branch, commit, date, changed files) or a plain copy
  if (Test-Path -LiteralPath (Join-Path $d.FullName '.git')) {
    $b = (& git -C $d.FullName rev-parse --abbrev-ref HEAD 2>$null)
    $c = (& git -C $d.FullName log -1 --format=%h 2>$null)
    $t = (& git -C $d.FullName log -1 --format=%cs 2>$null)
    $n = @(& git -C $d.FullName status --porcelain 2>$null).Count
    Write-Output ("repo|{0}|git|{1}|{2}|{3}|{4}|{5}|{6}" -f $d.Name, $b, $c, $t, $n, $v, $a)
  } else {
    Write-Output ("repo|{0}|copy|||||{1}|{2}" -f $d.Name, $v, $a)
  }
}
