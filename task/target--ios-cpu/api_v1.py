"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import datetime
import json
import os
import plistlib
import re
import tempfile

from task_c36be4b9314a45e0.api.ctask import InitCTask

# Every program runs inside this one bundle id: a free personal team allows ten app ids a week, and each new id
# would need its own development profile. --bundle_id changes it (a cache entry per device and bundle id)
BUNDLE_ID = 'org.ctuning.cmeta.runner'

# The iOS version the executables are built for (-miphoneos-version-min); --min_os changes it
MIN_OS = '16.0'

# Where Xcode keeps the development profiles it makes (Xcode 16 and newer, then older ones)
PROFILE_DIRS = ['~/Library/Developer/Xcode/UserData/Provisioning Profiles',
                '~/Library/MobileDevice/Provisioning Profiles']

# A minimal Xcode project with automatic signing. Built once per device, team and bundle id with
# "xcodebuild -allowProvisioningUpdates -allowProvisioningDeviceRegistration", Xcode registers the device in the
# team and makes the development profile - Xcode's own route, there is no command for that alone. Its codesign
# step fails in an ssh session (the login keychain is locked there), which does not matter: the profile is what
# is needed, and the programs are signed by setup-run through the user's session.
RUNNER = 'CMetaRunner'

RUNNER_MAIN = '''#include <stdio.h>
int main(int argc, char **argv) {
  printf("cmeta runner: %d argument(s)\\n", argc - 1);
  return 0;
}
'''

PBXPROJ = '''// !$*UTF8*$!
{
\tarchiveVersion = 1;
\tclasses = {
\t};
\tobjectVersion = 56;
\tobjects = {
\t\tA000000000000000000000A1 /* main.c in Sources */ = {isa = PBXBuildFile; fileRef = A000000000000000000000F1 /* main.c */; };
\t\tA000000000000000000000F1 /* main.c */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.c.c; path = main.c; sourceTree = "<group>"; };
\t\tA000000000000000000000F2 /* CMetaRunner.app */ = {isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = CMetaRunner.app; sourceTree = BUILT_PRODUCTS_DIR; };
\t\tA000000000000000000000G1 /* root */ = {isa = PBXGroup; children = (A000000000000000000000G2, A000000000000000000000G3); sourceTree = "<group>"; };
\t\tA000000000000000000000G2 /* CMetaRunner */ = {isa = PBXGroup; children = (A000000000000000000000F1); path = CMetaRunner; sourceTree = "<group>"; };
\t\tA000000000000000000000G3 /* Products */ = {isa = PBXGroup; children = (A000000000000000000000F2); name = Products; sourceTree = "<group>"; };
\t\tA000000000000000000000S1 /* Sources */ = {isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (A000000000000000000000A1); runOnlyForDeploymentPostprocessing = 0; };
\t\tA000000000000000000000T1 /* CMetaRunner */ = {
\t\t\tisa = PBXNativeTarget;
\t\t\tbuildConfigurationList = A000000000000000000000L2;
\t\t\tbuildPhases = (A000000000000000000000S1);
\t\t\tbuildRules = ();
\t\t\tdependencies = ();
\t\t\tname = CMetaRunner;
\t\t\tproductName = CMetaRunner;
\t\t\tproductReference = A000000000000000000000F2;
\t\t\tproductType = "com.apple.product-type.application";
\t\t};
\t\tA000000000000000000000P1 /* Project object */ = {
\t\t\tisa = PBXProject;
\t\t\tattributes = { LastUpgradeCheck = 1500; TargetAttributes = { A000000000000000000000T1 = { CreatedOnToolsVersion = 15.0; }; }; };
\t\t\tbuildConfigurationList = A000000000000000000000L1;
\t\t\tcompatibilityVersion = "Xcode 14.0";
\t\t\tdevelopmentRegion = en;
\t\t\thasScannedForEncodings = 0;
\t\t\tknownRegions = (en, Base);
\t\t\tmainGroup = A000000000000000000000G1;
\t\t\tproductRefGroup = A000000000000000000000G3;
\t\t\tprojectDirPath = "";
\t\t\tprojectRoot = "";
\t\t\ttargets = (A000000000000000000000T1);
\t\t};
\t\tA000000000000000000000C1 /* Debug (project) */ = {
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tSDKROOT = iphoneos;
\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = %(min_os)s;
\t\t\t\tCLANG_ENABLE_MODULES = NO;
\t\t\t\tONLY_ACTIVE_ARCH = NO;
\t\t\t};
\t\t\tname = Debug;
\t\t};
\t\tA000000000000000000000C2 /* Debug (target) */ = {
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tPRODUCT_NAME = CMetaRunner;
\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "%(bundle_id)s";
\t\t\t\tGENERATE_INFOPLIST_FILE = YES;
\t\t\t\tINFOPLIST_KEY_UILaunchScreen_Generation = YES;
\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";
\t\t\t\tSUPPORTED_PLATFORMS = iphoneos;
\t\t\t\tCODE_SIGN_STYLE = Automatic;
\t\t\t\tCODE_SIGN_IDENTITY = "Apple Development";
\t\t\t\tDEVELOPMENT_TEAM = %(team)s;
\t\t\t\tCURRENT_PROJECT_VERSION = 1;
\t\t\t\tMARKETING_VERSION = 1.0;
\t\t\t\tENABLE_BITCODE = NO;
\t\t\t};
\t\t\tname = Debug;
\t\t};
\t\tA000000000000000000000L1 /* project configurations */ = { isa = XCConfigurationList; buildConfigurations = (A000000000000000000000C1); defaultConfigurationIsVisible = 0; defaultConfigurationName = Debug; };
\t\tA000000000000000000000L2 /* target configurations */ = { isa = XCConfigurationList; buildConfigurations = (A000000000000000000000C2); defaultConfigurationIsVisible = 0; defaultConfigurationName = Debug; };
\t};
\trootObject = A000000000000000000000P1 /* Project object */;
}
'''

# A shared scheme: xcodebuild registers the destination device and makes the profile only for a scheme and a destination
SCHEME_REF = ('<BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "A000000000000000000000T1" '
              'BuildableName = "CMetaRunner.app" BlueprintName = "CMetaRunner" ReferencedContainer = "container:CMetaRunner.xcodeproj"/>')

SCHEME = '''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "1500" version = "1.7">
   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">
            %(ref)s
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <LaunchAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         %(ref)s
      </BuildableProductRunnable>
   </LaunchAction>
</Scheme>
'''


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo = None)


def _parse_time(text):
    """A profile's date as stored (ISO text), or None."""
    try:
        return datetime.datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _run(self,
             ctx: dict,
             cmd: str,
             timeout: int = None,
    ):
        """A command through the cmd task (a RUN: line in verbose mode): its return code, stdout and stderr."""

        r = self.cm.access({'category': self.category_alias + ',' + self.category_uid,
                            'command': 'run',
                            'ctx': ctx,
                            'arg1': 'cmd,c9ba0a88df394d7f',
                            'cmd': cmd,
                            'timeout': timeout,
                            'con': ctx['control'].get('con', False),
                            'quiet': ctx['control'].get('quiet', False),
                            'verbose': ctx['control'].get('verbose', False),
                            'text_cmd': 'RUN:',
                            'print_extra_line': False,
                            'capture_output': True,
                            'fail_if_nonzero_return_code': False})
        if self.cm.catch_error(r): return r

        return {'return': 0, 'returncode': r.get('returncode', 1), 'stdout': r.get('stdout') or '', 'stderr': r.get('stderr') or ''}

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        The device: the paired iPhones and iPads devicectl lists, one of them by --device (its name, UDID, serial
        number or model; the --use words of a program run are read here too, as the framework merges them after
        init), a question when several remain (-q takes the first).
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TASK target--ios-cpu init")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        xcode = ctx_tasks['global'].get('apple-xcode') or {}
        devicectl = xcode.get('qpath_devicectl') or 'xcrun devicectl'

        use = ((ctx_tasks.get('use') or {}).get('target--ios-cpu') or {})
        device = params.get('device') or use.get('device') or ''
        bundle_id = params.get('bundle_id') or use.get('bundle_id') or BUNDLE_ID

        fd, json_file = tempfile.mkstemp(prefix = 'cmeta-devicectl-', suffix = '.json')
        os.close(fd)
        try:
            r = self._run(ctx, f'{devicectl} list devices --timeout 15 --json-output {self.cm.q(json_file)}')
            if self.cm.catch_error(r): return r
            if r['returncode'] > 0:
                return self.cm.error(f'devicectl could not list the devices (return code {r["returncode"]}): '
                                     f'{(r["stderr"] or r["stdout"]).strip()}')
            try:
                with open(json_file, encoding = 'utf-8') as f:
                    devices = (json.load(f).get('result') or {}).get('devices') or []
            except (OSError, ValueError) as e:
                return self.cm.error(f'the device list of devicectl could not be read: {e}')
        finally:
            if os.path.isfile(json_file):
                os.remove(json_file)

        found = [d for d in devices if (d.get('hardwareProperties') or {}).get('platform') in ('iOS', 'iPadOS')]
        paired = [d for d in found if (d.get('connectionProperties') or {}).get('pairingState') == 'paired']
        if device:
            paired = [d for d in paired if self._matches(d, device)]

        if not paired:
            x = f' matching "{device}"' if device else ''
            if found and not device:
                hint = (' - a device that is listed but not paired must trust this Mac: unlock it and answer "Trust" '
                        'to "Trust This Computer?"')
            else:
                hint = (' - connect the device over USB, unlock it, trust this Mac when asked, and turn Developer Mode '
                        'on (Settings > Privacy & Security)')
            return self.cm.error(f'no paired iPhone or iPad found{x}{hint}')

        index = 0
        if len(paired) > 1:
            print ('')
            print (f'{space}More than one iOS device found:')
            print ('')
            for i, d in enumerate(paired):
                print (f'{space}{i}) {self._label(d)}')
            print ('')

            if quiet:
                print (f'{space}Quietly selected 0')
            else:
                from task_c36be4b9314a45e0.api.ctask import ask as ask_user
                r = ask_user(f'{space}Please select your device or press Enter for 0: ',
                             how = '-q (--quiet) to take the first of the list')
                if r['return'] > 0: return r
                x = r['answer'].strip()
                if x != '':
                    if not x.isdigit() or int(x) >= len(paired):
                        return self.cm.error(f'wrong device number selected in "{__file__}"')
                    index = int(x)

        selected = paired[index]

        # The local context, read again here: the tasks above may have changed it
        ctx['tasks']['local']['ios_udid'] = (selected.get('hardwareProperties') or {}).get('udid') or selected.get('identifier')
        ctx['tasks']['local']['ios_device'] = selected
        ctx['tasks']['local']['ios_bundle_id'] = bundle_id

        return {'return': 0}

    ############################################################
    def _matches(self, d, word):
        """The word names the device: its UDID, identifier, serial or ECID exactly, or a part of its name or model."""
        hp = d.get('hardwareProperties') or {}
        dp = d.get('deviceProperties') or {}
        w = str(word).strip().lower()
        if not w:
            return False
        exact = [hp.get('udid'), d.get('identifier'), hp.get('serialNumber'), str(hp.get('ecid') or '')]
        names = [dp.get('name'), hp.get('marketingName'), hp.get('productType')]
        return any(str(x).lower() == w for x in exact if x) or any(w in str(x).lower() for x in names if x)

    ############################################################
    def _label(self, d):
        hp = d.get('hardwareProperties') or {}
        dp = d.get('deviceProperties') or {}
        return (f"{dp.get('name')} ({hp.get('marketingName')}, {hp.get('productType')}, "
                f"iOS {dp.get('osVersionNumber')}, {hp.get('udid')})")

    ############################################################
    def run(self,
            ctx: dict,
            device: str = '',     # the name, UDID, serial number or model of the iPhone or iPad (the only paired one by default)
            bundle_id: str = '',  # the app id every program runs under, one development profile (org.ctuning.cmeta.runner)
            identity: str = '',   # a part of the name of the signing identity to use (the first "Apple Development" one by default)
            min_os: str = '',     # the iOS version the executables are built for (16.0)
            **kwargs
    ):
        """
        The device as devicectl describes it and what signing a program for it needs: the identity (a
        development certificate with its private key in the keychain), its team, the development profile for
        this device and bundle id (found among Xcode's, or made through the runner project - Xcode registers
        the device in the team then) and the entitlements of that profile.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **udid** (str), **bundle_id** (str), **min_os** (str)
                - **features** (dict): the device (name, model, iOS version, CPU type, ...)
                - **signing** (dict): identity, team, profile, entitlements, bundle_id
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        _local = ctx_tasks['local']
        work_dir = ctx_tasks['run_control']['work_dir']   # the cache entry of this device and bundle id

        xcode = ctx_tasks['global'].get('apple-xcode') or {}

        d = _local['ios_device']
        udid = _local['ios_udid']
        bundle_id = _local.get('ios_bundle_id') or bundle_id or BUNDLE_ID
        min_os = str(min_os or MIN_OS)

        hp = d.get('hardwareProperties') or {}
        dp = d.get('deviceProperties') or {}
        cp = d.get('connectionProperties') or {}

        features = {
          'platform': 'ios',
          'udid': udid,
          'identifier': d.get('identifier'),
          'serial_number': hp.get('serialNumber'),
          'name': dp.get('name'),
          'marketing_name': hp.get('marketingName'),
          'product_type': hp.get('productType'),
          'hardware_model': hp.get('hardwareModel'),
          'device_type': hp.get('deviceType'),
          'os_version': dp.get('osVersionNumber'),
          'os_build': dp.get('osBuildUpdate'),
          'cpu_type': (hp.get('cpuType') or {}).get('name'),
          'supported_cpu_types': [c.get('name') for c in (hp.get('supportedCPUTypes') or []) if c.get('name')],
          'arch_normalized': 'arm64',
          'arch_family': 'arm',
          'arch_bits': 64,
          'internal_storage_capacity': hp.get('internalStorageCapacity'),
          'developer_mode': dp.get('developerModeStatus'),
          'ddi_services_available': dp.get('ddiServicesAvailable'),
          'transport': cp.get('transportType'),
          'pairing': cp.get('pairingState'),
          'xcode_version': xcode.get('version'),
          'ios_sdk_version': xcode.get('ios_sdk_version'),
        }

        # The signing identity: the first "Apple Development" certificate with a private key (--identity picks another)
        r = self._identities(ctx)
        if self.cm.catch_error(r): return r
        identities = r['identities']

        chosen = None
        if identity:
            chosen = next((i for i in identities if identity.lower() in i['name'].lower()), None)
            if not chosen:
                return self.cm.error(f'no code-signing identity matches "{identity}" (security find-identity -p codesigning)')
        else:
            for prefix in ('Apple Development:', 'iPhone Developer:'):
                chosen = next((i for i in identities if i['name'].startswith(prefix)), None)
                if chosen: break
        if not chosen:
            return self.cm.error('no code-signing identity for iOS development on this Mac: in Xcode > Settings > Accounts '
                                 'add the Apple Account (+), select its team, Manage Certificates > + > Apple Development')

        r = self._team(ctx, chosen['name'])
        if self.cm.catch_error(r): return r
        team = r['team']

        # The development profile for this device and bundle id, made through the runner project when none exists
        r = self._find_profile(ctx, team, bundle_id, udid)
        if self.cm.catch_error(r): return r
        profile = r['profile']

        if not profile:
            if con:
                print ('')
                print (f'{space}INFO: no development profile of team {team} for {bundle_id} and this device: making one with Xcode ...')
            r = self._make_profile(ctx, work_dir, team, bundle_id, udid, min_os)
            if self.cm.catch_error(r): return r
            output = r['output']

            r = self._find_profile(ctx, team, bundle_id, udid)
            if self.cm.catch_error(r): return r
            profile = r['profile']
            if not profile:
                errors = '\n'.join(l for l in output.splitlines() if 'error' in l.lower())[-1500:]
                return self.cm.error(f'Xcode made no development profile of team {team} for {bundle_id} on device {udid}: '
                                     f'open "{os.path.join(work_dir, "runner", RUNNER + ".xcodeproj")}" in Xcode, select the '
                                     f'team and the device and build once (Signing & Capabilities tells what is missing)'
                                     + (f'\n{errors}' if errors else ''))

        entitlements = os.path.join(work_dir, 'entitlements.plist')
        with open(entitlements, 'wb') as f:
            plistlib.dump(profile['data'].get('Entitlements') or {}, f)

        expires = profile['data'].get('ExpirationDate')
        signing = {
          'identity': chosen['name'],
          'identity_hash': chosen['hash'],
          'team': team,
          'profile': profile['path'],
          'profile_name': profile['data'].get('Name'),
          'profile_expires': expires.isoformat() if isinstance(expires, datetime.datetime) else str(expires or ''),
          'entitlements': entitlements,
          'bundle_id': bundle_id,
        }

        if con:
            print ('')
            print (f'{space}INFO: iOS device: {self._label(d)}')
            print (f'{space}INFO: signing: {chosen["name"]} (team {team}), profile "{signing["profile_name"]}" '
                   f'until {signing["profile_expires"][:10]}')

        return {'return': 0,
                'udid': udid,
                'bundle_id': bundle_id,
                'min_os': min_os,
                'features': features,
                'signing': signing}

    ############################################################
    def _identities(self, ctx):
        """The code-signing identities of the keychains (all of them: in an ssh session the "valid" list is empty,
        since the login keychain is locked there, and the identities are still usable through the user's session)."""

        r = self._run(ctx, 'security find-identity -p codesigning')
        if self.cm.catch_error(r): return r

        identities = []
        for line in r['stdout'].splitlines():
            m = re.match(r'\s*\d+\)\s+([0-9A-Fa-f]{40})\s+"(.+)"\s*$', line)
            if m and not any(i['hash'] == m.group(1) for i in identities):
                identities.append({'hash': m.group(1), 'name': m.group(2)})

        return {'return': 0, 'identities': identities}

    ############################################################
    def _team(self, ctx, name):
        """The team of a certificate: the OU of its subject (the name in parentheses is the developer's own id)."""

        r = self._run(ctx, f'security find-certificate -p -c {self.cm.q(name)} | openssl x509 -noout -subject')
        if self.cm.catch_error(r): return r

        m = re.search(r'OU\s*=\s*([A-Z0-9]+)', r['stdout'])
        if not m:
            return self.cm.error(f'the team of the certificate "{name}" could not be read: {(r["stdout"] or r["stderr"]).strip()}')

        return {'return': 0, 'team': m.group(1)}

    ############################################################
    def _read_profile(self, ctx, path):
        """A provisioning profile (a CMS envelope around a plist), or None."""

        r = self._run(ctx, f'security cms -D -i {self.cm.q(path)}')
        if r['return'] > 0 or r['returncode'] > 0:
            return None
        try:
            return plistlib.loads(r['stdout'].encode('utf-8'))
        except Exception:
            return None

    ############################################################
    def _find_profile(self, ctx, team, bundle_id, udid):
        """The newest development profile of the team for the bundle id that provisions the device and has not expired."""

        app_id = f'{team}.{bundle_id}'
        now = _utcnow()
        best = None

        for d in PROFILE_DIRS:
            folder = os.path.expanduser(d)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if not name.endswith('.mobileprovision'):
                    continue
                path = os.path.join(folder, name)
                data = self._read_profile(ctx, path)
                if not data:
                    continue
                if (data.get('Entitlements') or {}).get('application-identifier') != app_id:
                    continue
                if udid not in (data.get('ProvisionedDevices') or []):
                    continue
                expires = data.get('ExpirationDate')
                if isinstance(expires, datetime.datetime) and expires <= now:
                    continue
                created = data.get('CreationDate') or datetime.datetime.min
                if best is None or created > (best['data'].get('CreationDate') or datetime.datetime.min):
                    best = {'path': path, 'data': data}

        return {'return': 0, 'profile': best}

    ############################################################
    def _write_runner_project(self, folder, bundle_id, team, min_os):
        proj = os.path.join(folder, RUNNER + '.xcodeproj')
        os.makedirs(os.path.join(folder, RUNNER), exist_ok = True)
        os.makedirs(os.path.join(proj, 'xcshareddata', 'xcschemes'), exist_ok = True)

        with open(os.path.join(folder, RUNNER, 'main.c'), 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write(RUNNER_MAIN)
        with open(os.path.join(proj, 'project.pbxproj'), 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write(PBXPROJ % {'bundle_id': bundle_id, 'team': team, 'min_os': min_os})
        with open(os.path.join(proj, 'xcshareddata', 'xcschemes', RUNNER + '.xcscheme'), 'w', encoding = 'utf-8', newline = '\n') as f:
            f.write(SCHEME % {'ref': SCHEME_REF})

        return proj

    ############################################################
    def _make_profile(self, ctx, work_dir, team, bundle_id, udid, min_os):
        """The runner project built for the device with automatic signing: Xcode registers the device in the team and
        makes the development profile. The build itself may fail (codesign in an ssh session); its output is returned."""

        folder = os.path.join(work_dir, 'runner')
        proj = self._write_runner_project(folder, bundle_id, team, min_os)

        cmd = (f'xcodebuild -project {self.cm.q(proj)} -scheme {RUNNER} -configuration Debug '
               f'-destination platform=iOS,id={udid} -derivedDataPath {self.cm.q(os.path.join(folder, "build"))} '
               f'-allowProvisioningUpdates -allowProvisioningDeviceRegistration build')
        r = self._run(ctx, cmd, timeout = 900)
        if self.cm.catch_error(r): return r

        return {'return': 0, 'output': (r['stdout'] + '\n' + r['stderr'])[-8000:]}

    ############################################################
    def _cached_result(self, path):
        """The result a cache entry stored, or None."""
        if not path:
            return None
        try:
            with open(os.path.join(path, 'cmeta-task-cached-result.json'), encoding = 'utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        if isinstance(data, dict) and isinstance(data.get('result'), dict):
            return data['result']
        return data if isinstance(data, dict) else None

    ############################################################
    def filter_cache_artifacts(self,
                               ctx: dict,
                               artifacts: list,
                               tmp_artifacts: list,
                               params: dict,
                               path: str = None,
                               **extra,
    ):
        """
        A cached target whose development profile expired (seven days for a free personal team) or disappeared is
        not reused: the run makes the target afresh, with a new profile.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        now = _utcnow()
        kept = []
        for a in artifacts:
            signing = (self._cached_result(a.get('path')) or {}).get('signing') or {}
            profile = signing.get('profile')
            expires = _parse_time(signing.get('profile_expires'))
            if profile and (not os.path.isfile(profile) or (expires and expires <= now)):
                if con:
                    why = 'expired' if os.path.isfile(profile) else 'is gone'
                    print (f'{space}INFO: the development profile of the cached iOS target {why}: making it again')
                continue
            kept.append(a)

        return {'return': 0, 'artifacts': kept, 'tmp_artifacts': tmp_artifacts}

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """What a cached result must carry fresh: the launcher source of this copy of the task (the main of every
        program, see src/cmeta_ios_main.c) and devicectl's path."""

        result['launcher_source'] = os.path.join(self.artifact_path, 'src', 'cmeta_ios_main.c')

        xcode = ctx['tasks']['global'].get('apple-xcode') or {}
        result['devicectl'] = xcode.get('qpath_devicectl') or 'xcrun devicectl'

        return {'return': 0}
