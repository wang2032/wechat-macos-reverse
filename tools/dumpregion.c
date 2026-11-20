/* dumpregion: write a memory range of a process to a file (hexdump-ish raw) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
int main(int argc,char**argv){
    if(argc<5){fprintf(stderr,"usage: %s pid addr len out\n",argv[0]);return 1;}
    pid_t pid=atoi(argv[1]);
    mach_vm_address_t addr=strtoull(argv[2],0,0);
    size_t len=strtoull(argv[3],0,0);
    mach_port_t task; if(task_for_pid(mach_task_self(),pid,&task)!=KERN_SUCCESS){fprintf(stderr,"tfp failed\n");return 2;}
    vm_offset_t d; mach_msg_type_number_t dc;
    kern_return_t kr=mach_vm_read(task,addr,len,&d,&dc);
    if(kr!=KERN_SUCCESS){fprintf(stderr,"read failed kr=%d\n",kr);return 3;}
    FILE*f=fopen(argv[4],"wb"); fwrite((void*)d,1,dc,f); fclose(f);
    fprintf(stderr,"wrote %u bytes from 0x%llx\n",dc,(unsigned long long)addr);
    mach_vm_deallocate(mach_task_self(),d,dc);
    return 0;
}
