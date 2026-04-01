"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
"""

import os
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
        if "." in urltail and "/" in urlhead:
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
    def run(self,
            ctx: dict,        # cMeta context
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
    ):

        """
        Download file.

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
        workdir = os.getcwd()

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
                        import shutil
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
            error = ''
            for u in range(0, len(urls)):
                url = urls[u]

                if len(files)>0:
                    filename = files[u]
                else:
                    filename = self._extract_filename_from_url(url)

                filename_with_path = os.path.join(path_to_files, filename)

                # Check if need to clean
                if os.path.isfile(filename_with_path) and clean:
                    os.remove(filename_with_path)

                # Download if doesn't exist
                if not os.path.isfile(filename_with_path):
                    if tool == 'cmeta':

                        rr = self.cm.utils.net.download(url, 
                                                        filename = filename + '.download',
                                                        path = directory, 
                                                        show_progress = con, 
                                                        fail_on_error = self.cm.fail_on_error, 
                                                        skip_ssl_certificate = skip_ssl_certificate, 
                                                        headers = headers,
                                                        api_key = api_key,
                                                        space = space,
                             )
                        if rr['return'] == 0:
                            success = True
                        else:
                            error = rr['error']

                    else:
                        return self.cm.error(f'download tool {tool} is not yet supported in "{__file__}" ({__name__})')
                else:
                    success = True

                if success:
                    f1 = filename + '.download'
                    f2 = filename

                    if directory:
                        f1 = os.path.join(directory, f1)
                        f2 = os.path.join(directory, f2)

                    os.replace(f1, f2)

                    if len(md5sums)>0:
                        md5sum = md5sums[u]

                        if verbose:
                            print ('')
                            print (f'{space}RUN: Checking md5sum for {filename}: {md5sum}')

                        r = self.cm.utils.files.md5sum(path = filename_with_path)
                        if self.cm.catch_error(r): return r

                        md5sum_calculated = r['md5sum']

                        if md5sum_calculated != md5sum:
                            error = f'md5sum failed: {md5sum_calculated}'
                            success = False

                if success:
                    break    

            if not success:
                x = ','.join(urls)
                return self.cm.error(f"failed downloading file from {x}\n{error}")

            filesize = os.path.getsize(filename_with_path)

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
                    if self.cm.catch_error(r): return r

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
                          'arg1': 'untar-file,a49b3cbd6f8f4bd6',
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
                    if self.cm.catch_error(rx): return rx

                else:
                    return self.cm.error(f'extension is not yet supported for unzip/untar {filename}')

                if clean_after_unzip and os.path.isfile(filename_with_path):
                    if verbose:
                        print (f'{space}RUN: rm {filename_with_path}')

                    os.remove(filename_with_path)

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

        if filename_with_path:
            result['path_to_file'] = filename_with_path

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

        return result
