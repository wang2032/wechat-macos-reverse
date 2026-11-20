/* ptry: test ptrace attach + text-page write permission
   usage: ptry <pid> <addr-hex> */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s pid addr-hex\n", argv[0]); return 1; }
    pid_t pid = atoi(argv[1]);
    mach_vm_address_t a = strtoull(argv[2], NULL, 16);
    errno = 0;
    int r = ptrace(PT_ATTACH, pid, 0, 0);
    printf("PT_ATTACH r=%d errno=%d (%s)\n", r, errno, strerror(errno));
    if (r != 0) return 2;
    int st = 0;
    pid_t w = waitpid(pid, &st, 0);
    printf("waitpid=%d status=0x%x wifstopped=%d sig=%d\n", w, st, WIFSTOPPED(st), WIFSTOPPED(st) ? WSTOPSIG(st) : -1);
    task_t t;
    kern_return_t kr = task_for_pid(mach_task_self(), pid, &t);
    printf("tfp kr=%d\n", kr);
    if (kr == KERN_SUCCESS) {
        mach_vm_address_t page = a & ~(mach_vm_address_t)0x3fff;
        unsigned int orig = 0; mach_vm_size_t out = 0; void *p = NULL;
        if (mach_vm_read(t, a, 4, (vm_offset_t*)&p, (mach_msg_type_number_t*)&out) == KERN_SUCCESS && p) {
            memcpy(&orig, p, 4); mach_vm_deallocate(mach_task_self(), (vm_offset_t)p, out);
        }
        printf("orig insn=0x%08x\n", orig);
        kr = mach_vm_protect(t, page, 0x4000, 0, VM_PROT_READ|VM_PROT_WRITE|VM_PROT_COPY);
        printf("protect kr=%d\n", kr);
        if (kr == KERN_SUCCESS) {
            unsigned int probe = orig; /* write same bytes back */
            kr = mach_vm_write(t, a, (vm_offset_t)&probe, 4);
            printf("write kr=%d\n", kr);
        }
    }
    errno = 0;
    r = ptrace(PT_DETACH, pid, 0, 0);
    printf("PT_DETACH r=%d errno=%d (%s)\n", r, errno, strerror(errno));
    return 0;
}
