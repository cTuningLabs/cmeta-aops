"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import importlib.util
import inspect
import os
import shutil
import stat

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        result = {'return':0}

        url = params.get('url')
        if not url:
            return self.cm.error(f'URL is not defined in "{__file__}" ({__name__})')

        filename = params.get('filename')

        urls = self._process_urls(url)
        files = self._process_files(filename)

        if files:
            filename = files[0]
        else:
            filename = self._extract_filename_from_url(urls[0])

        if not filename:
            if url:
                return self.cm.error(f'couldn\'t extract filename from {url} in "{__file__}" ({__name__})')
            return self.cm.error(f'filename is not defined in "{__file__}" ({__name__})')

        params['filename'] = filename

        return result


    ############################################################
    def customize_cache_artifact(self,
                                 ctx,
                                 cache_alias_template,
                                 cache_extra_alias,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        result = {'return':0}

        # It's dangerous because filenames can contain weird characters
        # Either clean it or rely on manually added cache_extra_alias

#        filename = params['filename']
#
#        if cache_extra_alias is None: 
#            cache_extra_alias = ''
#
#        if cache_extra_alias !='':
#            cache_extra_alias += self.cache_sep
#        cache_extra_alias += filename
#
#        result['cache_extra_alias'] = cache_extra_alias

        return result

    ############################################################
    def _extract_filename_from_url(self, url):

        urltail = os.path.basename(url)
        urlhead = os.path.dirname(url)

        filename = None
        if urltail and "/" in urlhead:
#        this doesn't detect filenames without extension!
#        if "." in urltail and "/" in urlhead:
            # Check if ? after filename
            j = urltail.find('?')
            if j>0:
                urltail=urltail[:j]
            filename = urltail

        return filename


    def _process_urls(self, url):

        if type(url) == list:
            urls = url
        else:
            if ',' in url:
                urls = url.split(',')
            else:
                urls = [url]

        return urls

    def _process_files(self, filename):
        files = []
        if filename:
            if type(filename) == list:
                files = filename
            else:
                if ',' in filename:
                    files = filename.split(',')
                elif filename != '':
                    files = [filename]

        return files

    ############################################################
    def common_sizes(self):
        """
        The size measures of the tool category (category/tool/api/common_sizes.py), shared with
        task/setup. Its package, tool_<uid>.api, exists once the engine has loaded the tool category in
        this process (any tool setup does that); before that, the module is loaded from the category's
        folder. None when the category is not plugged: the download then records no sizes.
        """
        try:
            from tool_c393ba5c6fa14f66.api import common_sizes
            return common_sizes
        except ImportError:
            pass
        r = self.cm.access({'category': 'category', 'command': 'find', 'arg1': 'tool,c393ba5c6fa14f66'})
        artifacts = r.get('artifacts') if r.get('return', 1) == 0 else None
        if not artifacts:
            return None
        path = os.path.join(artifacts[0]['path'], 'api', 'common_sizes.py')
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location('cmeta_aops_common_sizes', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    ############################################################
    def _md5sum_differs(self, path, filename, md5sum, verbose, space):
        """The md5sum of a file against the expected one: {'return': 0, 'differs': bool, 'md5sum': <of the file>}."""
        if verbose:
            print ('')
            print (f'{space}RUN: Checking md5sum for {filename}: {md5sum}')

        r = self.cm.utils.files.md5sum(path = path)
        if r['return'] > 0: return r

        return {'return': 0, 'differs': r['md5sum'] != md5sum, 'md5sum': r['md5sum']}

    ############################################################
    def _unpack_error(self, r, archive, downloaded_now):
        """
        The error of an unpack, with what to do when the archive was not downloaded by this attempt: an
        earlier one left it (cMeta before 0.34.2 could leave a cut download under its name), and the same
        request would fail on it every time.
        """
        if not downloaded_now and r.get('error'):
            r['error'] += (f'\nThe archive "{archive}" was left by an earlier attempt and was not downloaded again: '
                           'if it is incomplete or damaged, delete this file and repeat the command')
        return r

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            chdir: str = None,
            chdir_and_stay: str = None,
            mkdir: str = None,
            url: str = None,    
            env: dict = {},
            skip_ssl_certificate: bool = False,
            filename: str = None,
            md5sum: str = None,
            check_file: bool = False,
            directory: str = None,
            headers: dict = None,
            api_key: str = None,
            tool: str = 'cmeta',
            unzip: bool = False,
            unzip_overwrite: bool = True,
            clean_after_unzip: bool = False,
            strip_folders: int = 0,
            timeout: int = None,
            make_check_file_executable: bool = False,
            resume: bool = True,
    ):

        """
        Download file.

        A file gets its name only when it is complete: the engine compares what arrived with the size
        the server announced (a connection cut mid-way is an error, since cMeta 0.34.2), and a checksum
        (md5sum), when there is one, is compared before the name is given. Until then the bytes are in
        "<filename>.download" in the working directory, and an interrupted download continues from them
        on the next attempt (resume, on by default: an HTTP range request for the rest, only when the
        server confirms that the file is still the same one; --resume- starts over every time).

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK download run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        _params = {}

        if not url:
            return self.cm.error(f'URL is not defined in "{__file__}" ({__name__})')

        # Check if multiple URLs, files and md5sums
        urls = self._process_urls(url)

        files = self._process_files(filename)

        md5sums = []
        if md5sum:
            if type(md5sum) == list:
                md5sums = md5sum
            else:
                if ',' in md5sum:
                    md5sums = md5sum.split(',')
                elif md5sum != '':
                    md5sums = [md5sum]

        ###################################################################
        cur_dir = os.getcwd()

        workdir = cur_dir

        if mkdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: mkdir -p "{chdir}"')
            os.makedirs(mkdir, exist_ok=True)

        if chdir:
            if con and verbose:
                print ('')
                print (f'{space}INFO: cd "{chdir}"')
            os.chdir(chdir)
            workdir = chdir

        elif chdir_and_stay:
            if con and verbose:
                print ('')
                print (f'{space}INFO: cd "{chdir_and_stay}"')
            os.chdir(chdir_and_stay)
            workdir = chdir_and_stay

        if not directory:
            path_to_files = workdir
        else:
            if not self.cm.utils.files.is_dir_within_path(workdir, directory):
                return self.cm.error(f'"{directory}" should not go out of the working directory "{workdir}"')

            path_to_files = os.path.join(workdir, directory)

            if os.path.isdir(path_to_files):
                if clean:
                    if con and verbose:
                        print ('')
                        print (f'{space}RUN: rm {path_to_files}')

                    r = self.cm.utils.files.remove_files_and_dirs_in_path(path_to_files)
                    if self.cm.catch_error(r): return r

                    try:
                        shutil.rmtree(path_to_files)
                    except Exception as e:
                        return self.cm.error(f'can\'t remove directory "{path_to_files}"')

            if not os.path.isdir(path_to_files):
                os.makedirs(path_to_files)

        ###################################################################
        # Check file
        result = {'return':0}

        check_file_with_path = None
        if check_file:
            check_file_with_path = os.path.normpath(os.path.join(path_to_files, check_file))

        filename_with_path = None
        filesize = None

        if not check_file_with_path or not os.path.isfile(check_file_with_path):

            ###################################################################
            rr = {}

            success = False
            downloaded_now = False
            error = ''

            # The partial file of a download ("<name>.download") and the record that lets the engine continue
            # it ("<name>.download.resume") live in the working directory, not in `directory`: the tools ask
            # for a clean `directory` on every attempt, and an interrupted download of 1 GB must not start
            # over for that. A file gets its name only when it is complete and its checksum is right.
            part_dir = os.getcwd()

            # resume=False: every download starts at its first byte. The engine continues partial files
            # since 0.34.2; an older one always starts over
            download_extra = {}
            if resume and 'resume' in inspect.signature(self.cm.utils.net.download).parameters:
                download_extra['resume'] = True

            for u in range(0, len(urls)):
                url = urls[u]

                # Names are matched to URLs by position. There may be fewer of
                # them than URLs - init() always resolves a single filename, so
                # with several URLs (mirrors) every entry after the first has to
                # fall back to deriving its own name, otherwise the mirrors are
                # unreachable behind an IndexError.
                if len(files)>u:
                    filename = files[u]
                else:
                    filename = self._extract_filename_from_url(url)

                filename_with_path = os.path.join(path_to_files, filename)
                part_with_path = os.path.join(part_dir, filename + '.download')

                # Same positional matching as the filenames above: no check
                # for a mirror that has no checksum of its own
                expected_md5sum = md5sums[u] if len(md5sums)>u else None

                # Until 0.45.0 the partial file was in `directory`: one left there by an interrupted run of
                # that time cannot be continued (no record) and is dropped
                if directory:
                    old_part = os.path.join(path_to_files, filename + '.download')
                    if os.path.isfile(old_part):
                        os.remove(old_part)

                # Check if need to clean
                if os.path.isfile(filename_with_path) and clean:
                    os.remove(filename_with_path)

                # A file that an earlier attempt left under its name is taken as it is, unless it has a
                # checksum to answer to: until 0.45.0 the checksum was compared only right after a download,
                # so the attempt after a failed check took the bad file
                if os.path.isfile(filename_with_path) and expected_md5sum:
                    r = self._md5sum_differs(filename_with_path, filename, expected_md5sum, verbose, space)
                    if self.cm.catch_error(r): return r

                    if r['differs']:
                        if con:
                            print (f'{space}WARNING: {filename} was left by an earlier attempt with md5sum {r["md5sum"]} '
                                   f'instead of {expected_md5sum}: downloading it again')
                        os.remove(filename_with_path)

                # Download if doesn't exist
                if not os.path.isfile(filename_with_path):
                    if tool == 'cmeta':

                        rr = self.cm.utils.net.download(url,
                                                        filename = filename + '.download',
                                                        path = part_dir,
                                                        show_progress = con,
                                                        fail_on_error = self.cm.fail_on_error,
                                                        skip_ssl_certificate = skip_ssl_certificate,
                                                        headers = headers,
                                                        api_key = api_key,
                                                        space = space,
                                                        **download_extra,
                             )
                        if rr['return'] == 0:
                            if rr.get('resumed_from') and con and verbose:
                                print (f'{space}INFO: the download of {filename} continued after its first {rr["resumed_from"]} bytes')

                            complete = True

                            if expected_md5sum:
                                r = self._md5sum_differs(part_with_path, filename, expected_md5sum, verbose, space)
                                if self.cm.catch_error(r): return r

                                if r['differs']:
                                    # Not the file that was asked for: it never gets its name, and nothing of
                                    # it is kept for a next attempt to continue
                                    error = f'md5sum failed: {r["md5sum"]} instead of {expected_md5sum}'
                                    complete = False
                                    os.remove(part_with_path)

                            if complete:
                                try:
                                    os.replace(part_with_path, filename_with_path)
                                except OSError:
                                    # `directory` on another file system than the working directory (a link, a mount)
                                    shutil.move(part_with_path, filename_with_path)
                                success = True
                                downloaded_now = True
                        else:
                            error = rr['error']

                    else:
                        return self.cm.error(f'download tool {tool} is not yet supported in "{__file__}" ({__name__})')
                else:
                    success = True

                    # The file is there: what an interrupted download of it left is of no use any more
                    for leftover in (part_with_path, part_with_path + getattr(self.cm.utils.net, 'RESUME_RECORD_SUFFIX', '.resume')):
                        if os.path.isfile(leftover):
                            os.remove(leftover)

                if success:
                    break

            if not success:
                x = ','.join(urls)
                return self.cm.error(f"failed downloading file from {x}\n{error}")

            filesize = os.path.getsize(filename_with_path)

            # The sizes a setup takes at its peak: the archive and, after unpacking, the unpacked tree
            # (measured before the archive is removed by clean_after_unzip); task/setup records them.
            # common_sizes lives in the tool category: None when it cannot be loaded (nothing measured)
            sizes = self.common_sizes()
            unpacked_before = sizes.folder_bytes(path_to_files, skip = [filename_with_path]) if (unzip and sizes) else 0

            if unzip:
                if strip_folders and strip_folders != '': 
                    strip_folders = int(strip_folders)

                if filename.endswith('.zip'):
                    if verbose:
                        print ('')
                        print (f'{space}RUN: unzip {filename_with_path}')

                    r = self.cm.utils.files.unzip(filename_with_path, 
                                                  path = directory, 
                                                  remove_directories = strip_folders,
                                                  overwrite = unzip_overwrite, 
                                                  clean = clean_after_unzip,
                                                  fail_on_error = self.cm.fail_on_error)
                    if self.cm.catch_error(r): return self._unpack_error(r, filename_with_path, downloaded_now)

                elif (filename.endswith('.tar.xz') or \
                      filename.endswith('.tar.gz') or \
                      filename.endswith('.tar.bz2') or \
                      filename.endswith('.tgz')):

                    if verbose:
                        print ('')
                        print (f'{space}RUN: untar {filename_with_path}')

                    ii = {'ctx': ctx,
                          'category': self.category_alias + ',' + self.category_uid,
                          'command': 'run',
                          'arg1': 'untar,a49b3cbd6f8f4bd6',
                          'con': con, 
                          'quiet': quiet,
                          'verbose': verbose, 
                          'filename': filename_with_path,
                          'env': env,
                          'directory': directory,
                          'clean_after_untar': clean_after_unzip,
                          'strip_folders': strip_folders,
                          'timeout': timeout,
                    }

                    rx = self.cm.access(ii)
                    if self.cm.catch_error(rx): return self._unpack_error(rx, filename_with_path, downloaded_now)

                else:
                    return self.cm.error(f'extension is not yet supported for unzip/untar {filename}')

                unpacked_bytes = (sizes.folder_bytes(path_to_files, skip = [filename_with_path]) - unpacked_before) if sizes else 0
                download_sizes = {'url': urls[0] if urls else url, 'download_bytes': filesize,
                                  'unpacked_bytes': max(unpacked_bytes, 0), 'peak_bytes': filesize + max(unpacked_bytes, 0)}

                if clean_after_unzip and os.path.isfile(filename_with_path):
                    if verbose:
                        print (f'{space}RUN: rm {filename_with_path}')

                    os.remove(filename_with_path)
            else:
                download_sizes = {'url': urls[0] if urls else url, 'download_bytes': filesize,
                                  'unpacked_bytes': 0, 'peak_bytes': filesize}

            result['download_sizes'] = download_sizes
            if sizes:
                sizes.record_download_sizes(workdir, download_sizes)

        ###################################################################
        # Check file again
        if check_file_with_path:
            if not os.path.isfile(check_file_with_path):
                return self.cm.error(f'couldn\'t find check file "{check_file_with_path}"')

            result['check_file'] = check_file
            result['path_to_check_file'] = check_file_with_path

        if make_check_file_executable and os.name != 'nt':
            st = os.stat(check_file)
            os.chmod(check_file, st.st_mode | stat.S_IXUSR)

        result['path_to_files'] = path_to_files
        result['qpath_to_files'] = self.cm.q(path_to_files)

        if filename_with_path:
            result['path_to_file'] = filename_with_path
            result['qpath_to_file'] = self.cm.q(filename_with_path)

        if filesize:
            result['file_size'] = filesize

        if con:
            if verbose:
                print ('')
                if filename_with_path:
                    print (f'{space}FILE: downloaded {filename_with_path}')
                print (f'{space}PATH: downloaded files {path_to_files}')
            else:
                if filename_with_path:
                    print (f'{space}Downloaded file: {filename_with_path}')
                else:
                    print (f'{space}Path to files: {path_to_files}')

        if chdir:
#            if con and verbose:
#                print ('')
#                print (f'{space}INFO: cd "{cur_dir}"')
            os.chdir(cur_dir)

        return result

