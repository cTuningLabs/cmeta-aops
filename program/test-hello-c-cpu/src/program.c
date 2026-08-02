#include <stdio.h>

int main(int argc, char** argv) {
    const char* who = argc > 1 ? argv[1] : "world";
    printf("Hello, %s!\n", who);

    FILE* f = fopen("tmp-cmeta-program-stats.json", "w");
    if (f) {
        fprintf(f, "{\"hello\": \"%s\"}\n", who);
        fclose(f);
    }

    return 0;
}
