/* probe: find x'<hex...> key-literal patterns in memory */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#define CHUNK (4u<<20)
static int ishex(int c){return (c>='0'&&c<='9')||(c>='a'&&c<='f')||(c>='A'&&c<='F');}
int main(int argc,char**argv){
    pid_t pid=atoi(argv[1]); int maxhits=argc>2?atoi(argv[2]):30;
    mach_port_t task; if(task_for_pid(mach_task_self(),pid,&task)!=KERN_SUCCESS){fprintf(stderr,"tfp fail\n");return 2;}
    mach_vm_address_t a=0; int hits=0; unsigned long long scanned=0;
    while(1){
        mach_vm_size_t size=0; vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t ic=VM_REGION_BASIC_INFO_COUNT_64; mach_port_t obj;
        if(mach_vm_region(task,&a,&size,VM_REGION_BASIC_INFO_64,(vm_region_info_t)&info,&ic,&obj)!=KERN_SUCCESS)break;
        if(size==0){a++;continue;}
        if(info.protection&VM_PROT_READ){
            mach_vm_address_t ca=a;
            while(ca<a+size){
                mach_vm_size_t cs=a+size-ca; if(cs>CHUNK)cs=CHUNK;
                vm_offset_t d; mach_msg_type_number_t dc;
                if(mach_vm_read(task,ca,cs,&d,&dc)==KERN_SUCCESS){
                    unsigned char*b=(unsigned char*)d; scanned+=dc;
                    for(size_t i=0;i+64<=dc;i++){
                        if(b[i]!='x'||b[i+1]!='\'')continue;
                        int n=0; while(i+2+n<dc&&ishex(b[i+2+n]))n++;
                        if(n<16)continue;
                        printf("hit @0x%llx hexrun=%d : ",(unsigned long long)(ca+i),n);
                        for(size_t k=i;k<i+2+n+2&&k<dc;k++){unsigned char c=b[k];putchar(c>=32&&c<127?c:'.');}
                        printf("\n");
                        if(++hits>=maxhits)goto done;
                    }
                    mach_vm_deallocate(mach_task_self(),d,dc);
                }
                ca+=cs;
            }
        }
        a+=size;
    }
done:
    fprintf(stderr,"scanned %llu MB hits=%d\n",scanned>>20,hits);
    return hits?0:3;
}
