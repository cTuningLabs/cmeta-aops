"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Intel's installers of its developer tools (oneAPI packages, VTune, ...), for the tools that install them (tool/oneapi
here, tool/vtune of a plugged repository): Intel's EULA, the silent command on Windows and on Linux, the installation
instance of a folder, and the commands that remove an instance again. What each tool installs (its release table, the
file it finds after the install) stays the tool's.
"""

import hashlib
import os

# Intel's End User License Agreement for Developer Tools: the user's to read and accept (--with.accept_eula=yes)
EULA_URL = 'https://www.intel.com/content/www/us/en/developer/articles/license/end-user-license-agreement.html'

# The Visual Studio versions Intel's installer integrates with (its -p=NEED_VS<year>_INTEGRATION switches)
VS_INTEGRATIONS = ('2017', '2019', '2022', '2026')


def truthy(value):
    return value is True or str(value).strip().lower() in ('true', '1', 'yes', 'on', 'accepted')


def instance_of(folder):
    """
    The installation instance of an install folder. Intel's installer keeps one install folder per instance
    ("default" is the user's own installs, in ~/intel/oneapi or /opt/intel/oneapi): a folder of the cMeta cache
    gets an instance of its own, named by the folder, so that every release installed there stands apart from the
    others and from the user's.
    """
    return 'cmeta-' + hashlib.sha256(os.path.abspath(folder).encode('utf-8')).hexdigest()[:12]


def components_words(components):
    """Intel's words for the components of a package to install (colon-separated), or '' for all of them."""
    names = [str(c).strip() for c in (components or []) if str(c).strip()]
    return f'--components {":".join(names)} ' if names else ''


def linux_command(installer, folder, extract, log, instance, packages, components = None):
    """
    Intel's installer without root, silently, into a folder of its own (everything after -a is the installer's).
    Its copies of the packages (1.4 GB, kept for a repair) go into a folder of the caller's too, instead of
    ~/intel/installercache. components: only those of the package.
    """
    return (f'sh "{installer}" -f "{extract}" -r yes -a --silent --eula accept --install-dir "{folder}" '
            f'--instance {instance} --intel-sw-improvement-program-consent decline {components_words(components)}'
            f'--log-dir "{log}" --download-cache "{packages}"')


def windows_command(installer, log, install_dir = '', gui = False, vs_integration = True, components = None):
    """
    Intel's installer on Windows. It asks for administrator rights itself; "start /wait" waits for it, and the
    downloaded file goes when the install worked.

    Silently by default. Without install_dir where Intel installs: beside the oneAPI the machine has (the folder of
    its installation instance), else its default folder; with it, in that folder. vs_integration False: no Visual
    Studio integration - Intel's installer then neither installs Visual Studio extensions nor registers its project
    converter (whose registration shows error windows on some machines), and does not end the programs that run from
    Visual Studio's folder while it updates them (an MSVC build that runs meanwhile). components: only those of the
    package (Intel's online installer then downloads only them).

    gui: Intel's own wizard instead, to watch it or to choose there - the folder, the licence and the Visual Studio
    integration are its pages.
    """
    if gui:
        return f'start "" /wait "{installer}" && del /q "{installer}"'
    where = f'--install-dir "{install_dir}" ' if install_dir else ''
    skip = '' if vs_integration else ''.join(f'-p=NEED_VS{year}_INTEGRATION=0 ' for year in VS_INTEGRATIONS)
    return (f'start "" /wait "{installer}" -s -a --silent --eula accept --intel-sw-improvement-program-consent decline '
            f'{components_words(components)}{where}{skip}--log-dir "{log}" && del /q "{installer}"')


def removal_commands(installer, products_text, instance):
    """
    How Intel's installer removes what an instance holds: one command per installed product of its list
    (installer --list-products --instance <id>: "<product id> <version> true ..."). [] when the list names none.
    """
    cmds = []
    for line in str(products_text or '').splitlines():
        words = line.split()
        if len(words) >= 3 and words[0].startswith('intel.') and words[2].lower() == 'true':
            cmds.append(f'"{installer}" --silent --action remove --product-id {words[0]} --product-ver "{words[1]}" '
                        f'--instance {instance} --eula accept')
    return cmds


def user_installer():
    """Intel's own installer of a user without root (where it removes an instance from again), or ''."""
    path = os.path.join(os.path.expanduser('~'), 'intel', 'oneapi', 'installer', 'installer')
    return path if os.path.isfile(path) else ''
