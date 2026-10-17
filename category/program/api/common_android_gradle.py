"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Hooks shared by programs inheriting template-android-gradle-app. The selected program's
metadata declares its task/category dependencies; sources remain in its declared cRef.
"""

from pathlib import Path

from .cprogram import InitCProgram


class InitAndroidGradleProgram(InitCProgram):
    def customize_android_project(self, ctx, desc, params, **misc):
        local = ctx['tasks']['local']
        meta = local['selected-program']['artifact']['cmeta']
        cref = (params.get('compile') or {}).get('project_cref') or local.get('android_project_cref', '')
        directory = (params.get('compile') or {}).get('project_dir') or ''
        r = self.cm.access({'category': meta['uses_categories']['task'], 'command': 'run',
                            'arg1': meta['uses_artifacts']['task::android-gradle-app'], 'ctx': ctx,
                            'action': 'prepare', 'project_cref': cref, 'project_dir': directory})
        if self.cm.catch_error(r, fail16=True): return r
        local = ctx['tasks']['local']
        source = r['project_dir']
        local['android_source_dir'] = source
        local['src_dir'] = source
        # The driver reads this list from the merged description after the all pipeline.
        # Declaring every input covers XML/icons/Gradle changes as well as Kotlin/Java.
        desc.setdefault('local_vars', {})['src_file_names'] = r['source_files']
        local['src_file_names'] = r['source_files']
        return {'return': 0}

    def finish_android_compile(self, ctx, **misc):
        local = ctx['tasks']['local']
        build = local['android-gradle-build']
        apk = Path(build['apk'])
        local['target_path_exe'] = str(apk)
        local['target_path_bin'] = str(apk.parent)
        local['target_exe'] = apk.name
        local['android_build'] = {k: build.get(k) for k in
                                  ('apk', 'sha256', 'package', 'version_name', 'version_code', 'workspace')}
        return {'return': 0}

    def finish_android_run(self, ctx, **misc):
        local = ctx['tasks']['local']
        ran = local['android-gradle-run']
        local.setdefault('result_files_data', {})['android_app'] = {
            'action': ran['action'], 'serial': ran['serial'], 'apk': ran.get('apk'),
            'package': local['android_package'],
        }
        return {'return': 0}
