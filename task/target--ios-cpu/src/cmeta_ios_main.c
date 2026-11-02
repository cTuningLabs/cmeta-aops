/*
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The main() of every program cMeta runs on an iPhone or iPad (compute ios-cpu). iOS starts an app in a read-only
place: this main enters the app's own Documents folder (where the program's output files go, and where devicectl
reads them from), removes the output files of the previous run named in CMETA_IOS_CLEAN (separated by ";"), calls
the program's own main - renamed cmeta_program_main by the compile flags of tool/apple.xcode.clang - writes its
exit code into tmp-cmeta-ios-exit.txt (devicectl does not report it) and stays a moment, so that "devicectl device
process launch --console" sees the process end rather than a process it never found.
*/

#undef main

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

int cmeta_program_main(int argc, char **argv);

int main(int argc, char **argv) {
  const char *home = getenv("HOME");
  const char *clean = getenv("CMETA_IOS_CLEAN");
  char path[4096];
  FILE *f;
  int rc;

  setvbuf(stdout, NULL, _IOLBF, 0);

  if (home != NULL) {
    snprintf(path, sizeof(path), "%s/Documents", home);
    mkdir(path, 0755);
    if (chdir(path) != 0) {
      fprintf(stderr, "cmeta: cannot enter %s\n", path);
    }
  }

  if (clean != NULL && *clean != '\0') {
    char *names = strdup(clean);
    char *save = NULL;
    char *name;
    for (name = strtok_r(names, ";", &save); name != NULL; name = strtok_r(NULL, ";", &save)) {
      if (*name != '\0') unlink(name);
    }
    free(names);
  }
  unlink("tmp-cmeta-ios-exit.txt");

  rc = cmeta_program_main(argc, argv);

  fflush(stdout);
  fflush(stderr);

  f = fopen("tmp-cmeta-ios-exit.txt", "w");
  if (f != NULL) {
    fprintf(f, "%d\n", rc);
    fclose(f);
  }

  usleep(500000);
  return rc;
}
