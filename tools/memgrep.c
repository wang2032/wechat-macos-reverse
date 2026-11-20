/* memgrep: scan a process's readable memory for an ASCII needle and dump context */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#define CHUNK (4u<<20)
int main(int argc,char**argv){
    if(argc<3){fprintf(stderr,"usage: %s pid needle [maxhits] [ctx]\n",argv[0]);return 1;}
    pid_t pid=atoi(argv[1]);
    unsigned char nb[512]; size_t nl=0; const char*needle=argv[2];
    if(!strncmp(needle,"hex:",4)){
        const char*hx=needle+4;
        for(size_t i=0;hx[i]&&hx[i+1]&&nl<512;i+=2){
            unsigned v; sscanf(hx+i,"%2x",&v); nb[nl++]=(unsigned char)v;
        }
        needle=(const char*)nb;
    } else nl=strlen(needle);
    int maxhits=argc>3?atoi(argv[3]):20; int ctx=argc>4?atoi(argv[4]):48;
    mach_port_t task; kern_return_t kr=task_for_pid(mach_task_self(),pid,&task);
    if(kr!=KERN_SUCCESS){fprintf(stderr,"task_for_pid kr=%d\n",kr);return 2;}
    mach_vm_address_t a=0; int hits=0; unsigned long long scanned=0;
    while(hits<maxhits){
        mach_vm_size_t size=0; vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t ic=VM_REGION_BASIC_INFO_COUNT_64; mach_port_t obj;
        kr=mach_vm_region(task,&a,&size,VM_REGION_BASIC_INFO_64,(vm_region_info_t)&info,&ic,&obj);
        if(kr!=KERN_SUCCESS)break;
        if(size==0){a++;continue;}
        if(info.protection&VM_PROT_READ){
            mach_vm_address_t ca=a;
            while(ca<a+size&&hits<maxhits){
                mach_vm_size_t cs=a+size-ca; if(cs>CHUNK)cs=CHUNK;
                vm_offset_t d; mach_msg_type_number_t dc;
                if(mach_vm_read(task,ca,cs,&d,&dc)==KERN_SUCCESS){
                    unsigned char*b=(unsigned char*)d; scanned+=dc;
                    for(size_t i=0;i+nl<=dc&&hits<maxhits;i++){
                        if(memcmp(b+i,needle,nl))continue;
                        size_t s=(i>(size_t)ctx)?i-ctx:0;
                        size_t e=i+nl+ctx; if(e>dc)e=dc;
                        printf("\n--- hit @0x%llx (region 0x%llx) ---\n",
                               (unsigned long long)(ca+i),(unsigned long long)a);
                        for(size_t k=s;k<e;k++){
                            unsigned char c=b[k];
                            putchar(c>=32&&c<127?c:'.');
                        }
                        printf("\nhex: ");
                        for(size_t k=s;k<e;k++) printf("%02x",b[k]);
                        printf("\n");
                        hits++;
                    }
                    mach_vm_deallocate(mach_task_self(),d,dc);
                }
                ca+=cs;
            }
        }
        a+=size;
    }
    fprintf(stderr,"\nscanned %llu MB, hits=%d\n",scanned>>20,hits);
    return hits?0:3;
}
