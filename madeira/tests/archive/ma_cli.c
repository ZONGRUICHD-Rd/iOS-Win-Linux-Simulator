// SPDX-License-Identifier: GPL-3.0-or-later
// Test driver for MadeiraArchive.c: ma_cli ARCHIVE DEST [MEM_LIMIT_MB]
// Prints "rc=<code> detail=<text> done=<bytes>" and exits with the code.
#include <stdio.h>
#include <stdlib.h>
#include "MadeiraArchive.h"

static int progress(void *ctx, uint64_t done, uint64_t total) {
    (void)total;
    *(uint64_t *)ctx = done;
    const char *cancel = getenv("MA_CANCEL_AT");
    return cancel && done >= strtoull(cancel, NULL, 10);
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: ma_cli ARCHIVE DEST [MEM_LIMIT_MB]\n"); return 2; }
    uint64_t limit = argc > 3 ? strtoull(argv[3], NULL, 10) << 20 : 0;
    uint64_t done = 0;
    char detail[512];
    int rc = ma_extract(argv[1], argv[2], limit, progress, &done, detail, sizeof detail);
    printf("rc=%d detail=%s done=%llu\n", rc, detail, (unsigned long long)done);
    return rc;
}
