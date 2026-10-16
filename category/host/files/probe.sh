# Read-only probe of a POSIX host (Linux, macOS, WSL, a container): one "key=value" line per fact and
# one "repo|..." line per cMeta repository. Run with a login shell ("bash -l -s" over ssh, stdin = this
# file) so that ~/.local/bin, brew and the user's profile are on PATH. Parsed by host/api/v1.py::probe.

# The machine and its OS
echo "hostname=$(hostname 2>/dev/null)"
echo "kernel=$(uname -sr 2>/dev/null)"
echo "arch=$(uname -m 2>/dev/null)"

if [ -f /etc/os-release ]; then
  . /etc/os-release
  echo "os=$PRETTY_NAME"
elif command -v sw_vers >/dev/null 2>&1; then
  echo "os=$(sw_vers -productName) $(sw_vers -productVersion)"
else
  echo "os=$(uname -s)"
fi

echo "uptime=$(uptime 2>/dev/null | sed 's/^ *//')"

# The OS's own id, which stays across reboots and renames (a hostname does not): only its hash is printed -
# the first 16 hex digits of sha256(the id in lowercase), as host/api/v1.py::system_id_of computes it
SID=""
if [ -s /etc/machine-id ]; then SID=$(cat /etc/machine-id 2>/dev/null)
elif [ -s /var/lib/dbus/machine-id ]; then SID=$(cat /var/lib/dbus/machine-id 2>/dev/null)
elif command -v ioreg >/dev/null 2>&1; then SID=$(ioreg -rd1 -c IOPlatformExpertDevice 2>/dev/null | awk -F'"' '/"IOPlatformUUID"/ {print $4; exit}')
fi
SID=$(printf '%s' "$SID" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

if [ -n "$SID" ]; then
  if command -v sha256sum >/dev/null 2>&1; then SH=$(printf '%s' "$SID" | sha256sum)
  elif command -v shasum >/dev/null 2>&1; then SH=$(printf '%s' "$SID" | shasum -a 256)
  else SH=""; fi
  SH=$(printf '%s' "$SH" | cut -c1-16)
  if [ -n "$SH" ]; then echo "system_id=$SH"; fi
fi

# The login
echo "user=$(id -un 2>/dev/null)"
echo "home=$HOME"

# Can this login do root work unattended? (an upgrade of the system needs it)
if [ "$(id -u 2>/dev/null)" = "0" ]; then echo "sudo=root"
elif ! command -v sudo >/dev/null 2>&1; then echo "sudo=none"
elif sudo -n true 2>/dev/null; then echo "sudo=passwordless"
else echo "sudo=password"; fi

# A command that may hang is capped where "timeout" exists
TO=""
if command -v timeout >/dev/null 2>&1; then TO="timeout 30"; fi

# The basic tools
echo "python=$(python3 --version 2>&1 | head -1)"
echo "uv=$(uv --version 2>&1 | head -1)"
echo "git=$(git --version 2>&1 | head -1)"

# Container engines: the client version, and whether the Docker daemon answers ("(daemon down)" when the
# client is there but Docker Desktop / dockerd is not running); "-" when not installed
if command -v docker >/dev/null 2>&1; then
  DV=$(docker --version 2>/dev/null | head -1 | sed 's/^Docker version //; s/,.*//')
  if $TO docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then echo "docker=$DV"; else echo "docker=$DV (daemon down)"; fi
else
  echo "docker=-"
fi

if command -v podman >/dev/null 2>&1; then
  echo "podman=$(podman --version 2>/dev/null | head -1 | sed 's/^podman version //')"
else
  echo "podman=-"
fi

# cMeta: its command, its version and its home, as cMeta itself reports them ("cx --version")
CX=$(command -v cx 2>/dev/null)
echo "cx=$CX"

if [ -n "$CX" ]; then
  V=$(cx --version 2>/dev/null)
  echo "cmeta_version=$(echo "$V" | grep -m1 -i 'cMeta version' | sed 's/.*version *//')"

  # The home: "cx --print-home" (a cMeta newer than 0.35.1); an older cMeta has no such flag and fails, and its home is the
  # "cMeta home path" line of "cx --version"
  H=$(cx --print-home 2>/dev/null) || H=""
  if [ -z "$H" ]; then H=$(echo "$V" | grep -m1 'cMeta home path' | sed 's/.*: *//'); fi
  echo "cmeta_home=$H"
else
  H=""
fi

# Without cx there is nobody to ask for the home: the variable, else the default folder
if [ -z "$H" ]; then H="${CMETA_HOME:-$HOME/CMETA}"; fi

# The disk of the user's folder, the GPU, the processors
if command -v df >/dev/null 2>&1; then
  echo "disk=$(df -h "$HOME" 2>/dev/null | tail -1 | awk '{print $4 " free of " $2 " (" $5 " used)"}')"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "gpu=$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)"
elif [ "$(uname -s)" = "Darwin" ]; then
  echo "gpu=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -m1 'Chipset Model' | sed 's/.*: *//')"
fi

echo "cpus=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null)"

# The registered repositories: every path cx knows ("cx repo find", plugged ones included), else the
# folders under <cMeta home>/repos. Per repository: git branch/commit/date/changed files or "copy", the
# _cmr.yaml version and artifact (alias,UID - how the AOPS repository is recognised whatever its folder
# is called). "git status" can be slow on a mounted tree (/mnt/d under WSL): capped at 30 s where
# "timeout" exists ("?" changed files when it runs out).
LIST=""
if [ -n "$CX" ]; then LIST=$(cx repo find 2>/dev/null); fi
if [ -z "$LIST" ] && [ -d "$H/repos" ]; then LIST=$(ls -d "$H"/repos/*/ 2>/dev/null); fi

printf '%s\n' "$LIST" | while IFS= read -r d; do
  d="${d%/}"
  [ -n "$d" ] && [ -d "$d" ] || continue
  n=$(basename "$d")

  # The version and the artifact of its descriptor
  v=""; a=""
  if [ -f "$d/_cmr.yaml" ]; then
    v=$(grep -m1 -E '^version:' "$d/_cmr.yaml" | sed 's/^version: *//' | tr -d "\"'")
    a=$(grep -m1 -E '^artifact:' "$d/_cmr.yaml" | sed 's/^artifact: *//' | tr -d "\"'")
  fi

  # A git clone (branch, commit, date, changed files) or a plain copy
  if [ -d "$d/.git" ]; then
    b=$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)
    c=$(git -C "$d" log -1 --format='%h' 2>/dev/null)
    t=$(git -C "$d" log -1 --format='%cs' 2>/dev/null)
    s=$($TO git -C "$d" status --porcelain 2>/dev/null); rc=$?
    if [ "$rc" = "124" ]; then m="?"; else m=$(printf '%s' "$s" | grep -c .); fi
    echo "repo|$n|git|$b|$c|$t|$m|$v|$a"
  else
    echo "repo|$n|copy|||||$v|$a"
  fi
done
