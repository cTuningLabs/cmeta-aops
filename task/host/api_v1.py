"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import sys
import struct
import copy
import shutil
import subprocess
import socket

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        # Just more user-friendly check for params (duplicate of "run")
        r = self.cm.check_params(params, ['env', 'bits', 'timeout'], __name__)
        if self.cm.catch_error(r): return r

        return {'return':0}


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            bits: int = None,
            timeout: int = 10,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        env_os = os.environ

        # Convert +keys to lists
        _env = env.copy()
        self.cm.utils.sys.plus_env(_env)

        result = {'return':0, 
                  'os_env':env_os.copy()
        }

        ##################################################################
        # Check various platform info
        pbits = 8 * struct.calcsize("P")

        if not bits:
            bits = 32
            if os.name == 'nt':
                # Trying to get fast way to detect bits
                if os.environ.get('ProgramW6432', '') != '' or os.environ.get('ProgramFiles(x86)', '') != '':  # pragma: no cover
                    bits = 64
            else:
                # On Linux use first getconf LONG_BIT and if doesn't work use python bits
                bits = pbits

                cmd = 'getconf LONG_BIT'

                r = self.cm.utils.sys.run(cmd, env = env, genv = env_os, timeout = timeout, capture_output = True,
                                          con = False, verbose = verbose, text_cmd = 'RUN', space = space)
                if self.cm.catch_error(r): return r
                if r['returncode'] == 0:
                    s = r['stdout'].strip()
                    if len(s) > 0 and len(s) < 4:
                        try:
                            bits = int(s)
                        except:
                            pass

        host_os = {}

        host_os['python_bits'] = pbits
        host_os['bits'] = bits

        host_os['python_platform_architecture'] = platform.architecture()
        host_os['python_platform_machine'] = platform.machine()
        host_os['python_platform_node'] = platform.node()
        host_os['python_platform_system'] = platform.system()
        host_os['python_platform_release'] = platform.release()
        host_os['python_platform_version'] = platform.version()
        host_os['python_platform'] = platform.platform()
        host_os['python_platform_terse'] = platform.platform(terse = True)
        host_os['python_platform_aliased'] = platform.platform(aliased = True)
        host_os['python_platform_uname'] = platform.uname()
        host_os['python_os_name'] = os.name
        host_os['python_os_cpu_count'] = os.cpu_count()
        host_os['python_sys_platform'] = sys.platform
        host_os['python_platform_processor'] = platform.processor()

        # OS name
        uname = ''

        if os.name == 'nt':
            uname = 'windows'
        else:
            uname = None
            cmd = 'uname'

            r = self.cm.utils.sys.run(cmd, env = env, genv = env_os, timeout = timeout, capture_output = True,
                                      con = False, verbose = verbose, text_cmd = 'RUN', space = space)
            if self.cm.catch_error(r): return r
            if r['returncode'] == 0:
                uname = r['stdout'].strip().lower()

        host_os['uname'] = uname

        # OS arch
        uarch = ''

        if os.name == 'nt':
            uarch = platform.machine().lower()
        else:
            # https://stackoverflow.com/questions/45125516/possible-values-for-uname-m

            cmd = 'uname -m'

            uarch = None

            r = self.cm.utils.sys.run(cmd, env = env, genv = env_os, timeout = timeout, capture_output = True,
                                      con = False, verbose = verbose, text_cmd = 'RUN', space = space)
            if self.cm.catch_error(r): return r
            if r['returncode'] == 0:
                uarch = r['stdout'].strip().lower()

            os_release = ''
            if os.path.isfile('/etc/os-release'):
                os_release_dict = {}
                try:
                    with open("/etc/os-release") as f:
                       os_release_dict = dict(line.strip().split("=", 1) for line in f if "=" in line)
                except:
                    pass

                host_os['release_name'] = f"{os_release_dict.get('PRETTY_NAME', 'Unknown')}".replace('"', '')

                kernel_version = os.uname().release

                host_os['release_name_with_kernel'] = f"{host_os['release_name']} ({kernel_version})"

        if uarch == 'x86_64': uarch = 'amd64'

        # May have armv6l, aarch64, riscv64 ...

        host_os['uarch'] = uarch

        # If Linux, detect extra env:
        if uname != 'windows':
            x = detect_linux_env()
            result['os_extra'] = x

            y = '1' if x.get('passwordless_sudo', False) else '0'
            result['passwordless_sudo_noninteractive_int'] = y
        else:
           # --source winget: without it winget also queries the Microsoft Store
           # source, and where that fails (0x8a15005e, certificate pinning broken
           # by an HTTPS-inspecting antivirus or proxy) winget refuses to install
           # a package it has already found in the winget source.
           result['os_extra'] = {
             "id": "windows",
             "id_like": "windows",
             "install_cmd": "winget install {{name}} --source winget",
             "install_cmd_sudo": "winget install {{name}} --source winget",
             "install_cmd_sudo_version": "winget install {{name}} --version {{version}} --source winget",
             "install_cmd_version": "winget install {{name}} --version {{version}} --source winget",
             "package_manager": "winget",
             "passwordless_sudo": True,
             "sudo": False,
           }

        # Finish automation
        result['os'] = host_os

        result['hostname'] = get_hostname_info()

        # Common vars
        all_vars = {
          'windows':{
            'clean_dir_quiet': 'rmdir /s /q',
            'file_ext_exe': '.exe',
            'file_ext_obj': '.obj',
            'file_ext_exe_search': '.exe',
            'file_ext_bat': '.bat',
            'file_ext_bat2': '.bat',
            'file_ext_cmd': '.cmd',
            'file_ext_cmd2': '.cmd',
            'file_ext_lib': '.lib',
            'file_ext_dlib': '.dll',
            'call_script': 'call',
            'start_exe_prefix': '',
            'cmd_sep': '&&',
            'cmd_new_line': '^',
            'os_sep': '\\',
            'os_pathsep': ';',
          },
          'linux':{
            'clean_dir_quiet': 'rm -rf',
            'file_ext_exe': '',
            'file_ext_obj': '.o',
            'file_ext_exe_search': '.',
            'file_ext_bat': '.sh',
            'file_ext_bat2': '',
            'file_ext_cmd': '.cmd',
            'file_ext_cmd2': '',
            'file_ext_lib': '.a',
            'file_ext_dlib': '.so',
            'call_script': '.',
            'start_exe_prefix': './',
            'cmd_sep': '&&',
            'cmd_new_line': '\\',
            'os_sep': '/',
            'os_pathsep': ':',
          },
          'darwin':{
            'clean_dir_quiet': 'rm -rf',
            'file_ext_exe': '',
            'file_ext_obj': '.o',
            'file_ext_exe_search': '.',
            'file_ext_bat': '.sh',
            'file_ext_bat2': '',
            'file_ext_cmd': '.cmd',
            'file_ext_cmd2': '',
            'file_ext_lib': '.a',
            'file_ext_dlib': '.dylib',
            'call_script': '.',
            'start_exe_prefix': './',
            'cmd_sep': '&&',
            'cmd_new_line': '\\',
            'os_sep': '/',
            'os_pathsep': ':',
          },
        }

        vars_os = uname if uname in all_vars else 'linux'
        
        result['vars'] = all_vars[vars_os]

        result['ck'] = {'version':self.cm.__version__}

        # Initialize for global use !
        result['_aggregate'] = {'env':_env}

        # Check if not Windows and ~/.local/bin exists but not in PATH:
        home = os.path.expanduser("~")

        host_os['home_path'] = home

        if os.name != 'nt':
            path_local_bin = os.path.join(home, '.local', 'bin')
            if os.path.isdir(path_local_bin) and path_local_bin not in os.environ.get('PATH',''):
                _path = _env.setdefault('+PATH', [])
                _path.append(path_local_bin)

        return result

###################################################################################################
def detect_linux_env():
    """
    Returns a dict like:
    {
        "id": "ubuntu",
        "id_like": "debian",
        "package_manager": "apt-get",
        "install_cmd": "apt-get install -y {{name}}",
        "install_cmd_version": "apt-get install -y {{name}}={{version}}",
        "cmd_sudo": "sudo ",
        "sudo": True,
        "passwordless_sudo": False,
    }
    """

    def parse_os_release():
        data = {}

        for path in ("/etc/os-release", "/usr/lib/os-release"):
            if not os.path.exists(path):
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue

                        key, value = line.split("=", 1)
                        value = value.strip()

                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                            value = value[1:-1]

                        data[key] = value

                if data:
                    return data
            except OSError:
                continue

        return data

    def choose_best_package_manager(distro_id, id_like):
        distro_id = (distro_id or "").strip().lower()
        like_tokens = [x.strip().lower() for x in (id_like or "").split() if x.strip()]

        present = {
            "brew": shutil.which("brew") is not None,
            "apt": shutil.which("apt") is not None,
            "apt-get": shutil.which("apt-get") is not None,
            "dnf": shutil.which("dnf") is not None,
            "microdnf": shutil.which("microdnf") is not None,
            "tdnf": shutil.which("tdnf") is not None,
            "yum": shutil.which("yum") is not None,
            "apk": shutil.which("apk") is not None,
            "pacman": shutil.which("pacman") is not None,
            "zypper": shutil.which("zypper") is not None,
            "xbps-install": shutil.which("xbps-install") is not None,
            "emerge": shutil.which("emerge") is not None,
            "nix-env": shutil.which("nix-env") is not None,
        }

        def first_present(candidates):
            for candidate in candidates:
                if present.get(candidate):
                    return candidate
            return None

        if distro_id == "darwin":
            return first_present(["brew"])

        if distro_id == "alpine":
            return first_present(["apk"])

        if distro_id in {"ubuntu", "debian", "linuxmint", "raspbian", "pop", "neon"} or "debian" in like_tokens:
            return first_present(["apt-get", "apt"])

        if distro_id == "amzn":
            return first_present(["dnf", "yum", "microdnf"])

        if distro_id == "azurelinux":
            return first_present(["tdnf", "dnf"])

        if distro_id == "fedora":
            return first_present(["dnf", "microdnf", "yum"])

        if distro_id in {"rhel", "rocky", "almalinux", "centos", "ol", "virtuozzo"}:
            return first_present(["dnf", "microdnf", "yum"])

        if "rhel" in like_tokens or "fedora" in like_tokens or "centos" in like_tokens:
            return first_present(["dnf", "microdnf", "yum"])

        if distro_id in {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles", "sled"} or "suse" in like_tokens:
            return first_present(["zypper"])

        if distro_id in {"arch", "manjaro", "endeavouros"} or "arch" in like_tokens:
            return first_present(["pacman"])

        if distro_id == "void":
            return first_present(["xbps-install"])

        if distro_id == "gentoo":
            return first_present(["emerge"])

        if distro_id == "nixos" or "nixos" in like_tokens:
            return first_present(["nix-env"])

        return first_present([
            "apt-get",
            "apt",
            "dnf",
            "microdnf",
            "yum",
            "apk",
            "zypper",
            "pacman",
            "xbps-install",
            "emerge",
            "nix-env",
        ])

    def install_command_for(package_manager):
        commands = {
            "brew": "brew install {{name}}",
            "apt": "apt install -y {{name}}",
            "apt-get": "apt-get install -y {{name}}",
            "dnf": "dnf install -y {{name}}",
            "tdnf": "tdnf install -y {{name}}",
            "microdnf": "microdnf install -y {{name}}",
            "yum": "yum install -y {{name}}",
            "apk": "apk add {{name}}",
            "pacman": "pacman -S --noconfirm {{name}}",
            "zypper": "zypper --non-interactive install {{name}}",
            "xbps-install": "xbps-install -y {{name}}",
            "emerge": "emerge {{name}}",
            "nix-env": "nix-env -iA nixpkgs.{{name}}",
        }
        return commands.get(package_manager)

    def install_command_for_version(package_manager):
        commands_version = {
            "brew": "brew install {{name}}@{{version}}",
            "apt": "apt install -y {{name}}={{version}}",
            "apt-get": "apt-get install -y {{name}}={{version}}",
            "dnf": "dnf install -y {{name}}-{{version}}",
            "tdnf": "tdnf install -y {{name}}-{{version}}",
            "microdnf": "microdnf install -y {{name}}-{{version}}",
            "yum": "yum install -y {{name}}-{{version}}",
            "apk": "apk add {{name}}={{version}}",
            "pacman": "pacman -S --noconfirm {{name}}",
            "zypper": "zypper --non-interactive install {{name}}={{version}}",
            "xbps-install": "xbps-install -y {{name}}-{{version}}",
            "emerge": "emerge ={{name}}-{{version}}",
            "nix-env": "nix-env -iA nixpkgs.{{name}}",
        }
        return commands_version.get(package_manager)

    def detect_sudo():
        sudo_path = shutil.which("sudo")
        if not sudo_path:
            return False, False

        try:
            result = subprocess.run(
                [sudo_path, "-n", "true"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            passwordless = (result.returncode == 0)
        except Exception:
            passwordless = False

        return True, passwordless

    os_name = platform.system().strip().lower()

    if os_name == "darwin":
        distro_id = "darwin"
        # Compatibility alias requested by caller-side logic.
        id_like = "debian"
    else:
        os_info = parse_os_release()
        distro_id = os_info.get("ID")
        id_like = os_info.get("ID_LIKE")

    if distro_id == 'azurelinux' and id_like is None:
        id_like = 'azurelinux'

    if distro_id == 'debian' and id_like is None:
        id_like = 'debian'

    package_manager = choose_best_package_manager(distro_id, id_like)
    cmd = install_command_for(package_manager)
    cmd_version = install_command_for_version(package_manager)

    sudo_installed, passwordless_sudo = detect_sudo()
    sudo_cmd = 'sudo ' if sudo_installed else ''
    cmd_sudo = f"sudo {cmd}" if sudo_installed else cmd
    cmd_sudo_version = f"sudo {cmd_version}" if sudo_installed else cmd_version

    return {
        "id": distro_id,
        "id_like": id_like,
        "package_manager": package_manager,
        "install_cmd": cmd,
        "install_cmd_version": cmd_version,
        "install_cmd_sudo": cmd_sudo,
        "install_cmd_sudo_version": cmd_sudo_version,
        "sudo": sudo_installed,
        "sudo_cmd": sudo_cmd,
        "passwordless_sudo": passwordless_sudo,
    }

###################################################################################################
def get_hostname_info():
    result = {
        "hostname": None,
        "ipv4": None,
        "ipv6": None,
        "ipv4_default": None,
        "ipv6_default": None,
    }

    # --- Hostname ---
    try:
        result["hostname"] = socket.gethostname()
    except Exception:
        pass

    ipv4_set = set()
    ipv6_set = set()

    # --- Helper: outbound IP (best/default IP) ---
    def get_outbound_ip(family, target):
        try:
            s = socket.socket(family, socket.SOCK_DGRAM)
            try:
                s.connect(target)
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:
            return None

    # Get default IPs first (most important)
    ipv4_default = get_outbound_ip(socket.AF_INET, ("8.8.8.8", 80))
    ipv6_default = get_outbound_ip(socket.AF_INET6, ("2001:4860:4860::8888", 80))

    result["ipv4_default"] = ipv4_default
    result["ipv6_default"] = ipv6_default

    if ipv4_default:
        ipv4_set.add(ipv4_default)
    if ipv6_default:
        ipv6_set.add(ipv6_default)

    # --- Hostname resolution (adds more IPs) ---
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None)
        for family, _, _, _, sockaddr in infos:
            ip = sockaddr[0]
            if family == socket.AF_INET:
                ipv4_set.add(ip)
            elif family == socket.AF_INET6:
                ipv6_set.add(ip)
    except Exception:
        pass

    # --- Cleanup helper ---
    def finalize(ip_set):
        if not ip_set:
            return None

        # Prefer non-loopback addresses
        non_loopback = [
            ip for ip in ip_set
            if not ip.startswith("127.") and ip != "::1"
        ]

        return non_loopback if non_loopback else list(ip_set)

    result["ipv4"] = finalize(ipv4_set)
    result["ipv6"] = finalize(ipv6_set)

    return result

