#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>
#include <libgen.h>

#define TAIL_SIZE 16000
#define TAG "<nexe~~sentinel>"
#define RESOURCE_OFFSET 46

typedef struct {
    double contentSize;
    double resourceSize;
} info_t;

int mkpath(char *dir, mode_t mode) {

    if (strlen(dir) == 1 && (dir[0] == '/' || dir[0] == '.'))
        return 0;

    mkpath(dirname(strdupa(dir)), mode);

    return mkdir(dir, mode);
}

unsigned long extract(int fd, unsigned long offset, unsigned long size, char *out) {
    char buf[4096];
    int r;
    int outfd;
    unsigned long origSize = size;
    unsigned long lineEnd = 0;
    
    outfd = open(out, O_WRONLY|O_CREAT|O_TRUNC, 0666);
    if (outfd == -1) {
        fprintf(stderr, "opening %s: %s\n", out, strerror(errno));
        exit(1);
    }

    printf("Extracting data at 0x%lx (size 0x%lx) to file %s\n", offset, size, out);
    if (lseek(fd, offset, SEEK_SET) == -1) {
        perror("lseek");
        exit(1);
    }
    while ((r = read(fd, buf, sizeof(buf) < size ? sizeof(buf) : size)) > 0) {
        if (!lineEnd) {
            char *ptr = memchr(buf, '\n', r);
            if (ptr) {
                lineEnd = (ptr - buf) + (origSize - size);
            }
        }
        if (write(outfd, buf, r) != r) {
            perror("write");
            exit(1);
        }
        size -= r;
    }
    if (r == -1) {
        perror("read");
        exit(1);
    }
    close(outfd);
    return lineEnd;
}

int main(int argc, char **argv) {

    if (argc != 4) {
        printf("%s: <input> <output content> <output resource>\n", argv[0]);
        exit(1);
    }

    int fd;
    fd = open(argv[1], O_RDONLY);
    if (fd == -1) {
        perror("open input file");
        exit(-1);
    }
    printf("File opened: %s\n", argv[1]);
    int tail_offset;
    tail_offset = lseek(fd, -TAIL_SIZE, SEEK_END);

    if (tail_offset == -1) {
        perror("lseek");
        exit(-1);
    }
    char buf[TAIL_SIZE];
    int r;
    r = read(fd, buf, TAIL_SIZE);
    if (r == -1) {
        perror("read");
        exit(1);
    }
    if (r != TAIL_SIZE) {
        fprintf(stderr, "short read: %u instead of %u\n", r, TAIL_SIZE);
    }
    char *s = memmem(buf, TAIL_SIZE, TAG, strlen(TAG));
    if (!s) {
        fprintf(stderr, "Can't find info block\n");
        exit(1);
    }
    int infoOffset = (s - buf) + tail_offset;
    printf("Found info block header at offset: 0x%x\n", infoOffset);

    info_t *info = (void*)(s + strlen(TAG));
    unsigned long contentSize = info->contentSize;
    unsigned long resourceSize = info->resourceSize;
    printf("Content Size: %lx\n", contentSize);
    printf("Resource Size: %lx\n", resourceSize);

    unsigned long contentOffset = infoOffset - resourceSize - contentSize;
    unsigned long resourceOffset = infoOffset - resourceSize;
    printf("Found content at offset: %lx\n", contentOffset);
    printf("Found resource at offset: %lx\n", resourceOffset);

    unsigned long lineEnd = extract(fd, contentOffset, contentSize, argv[2]) - RESOURCE_OFFSET;    
    extract(fd, resourceOffset, resourceSize, argv[3]); 

    if (lseek(fd, contentOffset + RESOURCE_OFFSET, SEEK_SET) == -1) {
        perror("lseek");
        exit(1);
    }
    
    char *resourceDesc = malloc(lineEnd);
    if (!resourceDesc) {
        perror("malloc");
        exit(1);
    }

    r = read(fd, resourceDesc, lineEnd);
    if (r == -1) {
        perror("read");
        exit(1);
    }
    if (r != lineEnd) {
        fprintf(stderr, "short read");
        exit(1);
    }
    char *oldPtr = resourceDesc;
    char *ptr = strtok(resourceDesc, ",");
    int i = 0;
    while (ptr) {
        ptr = strtok(NULL, ",");
        if (ptr && *oldPtr && !i) {
            *(ptr - 1) = ',';

            char *fileName = oldPtr + 1;
            char *fileNameEnd = strchr(fileName, '"');
            if (fileNameEnd) {
                *fileNameEnd = 0;
                fileNameEnd++;
                if (*fileNameEnd) {
                    unsigned long offset, size;
                    sscanf(fileNameEnd, ":[%lu,%lu]", &offset, &size);
                    mkpath(dirname(strdupa(fileName)), 0755);
                    extract(fd, resourceOffset + offset, size, fileName);
                }
            }
        }
        oldPtr = ptr;
        i ^= 1;
    }
   

    free(resourceDesc);
    close(fd);
    printf("All done.\n");
}

