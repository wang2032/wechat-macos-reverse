/*
 * scan_keys.c — WeChat 4.x (macOS) SQLCipher key scanner
 *
 * WeChat 4.x opens each DB with SQLCipher raw-key syntax:
 *     PRAGMA key = "x'<32-byte key hex><16-byte salt hex>'"
 * That 99-byte string stays resident in the heap while the DB is open,
 * so we scan readable memory for  x' <96 hex> '  and map each key to a DB
 * by matching the salt against the first 16 bytes of the .db file.
 *
 * Requires: target signed non-hardened, or SIP disabled + 'com.apple.security.cs.debugger'
 * Usage:    ./scan_keys [pid] [out.json]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <ftw.h>
#include <pwd.h>
#include <sys/stat.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>

#define MAX_DBS   512
#define MAX_KEYS  1024
#define HEXLEN    96          /* 64 key + 32 salt */
#define PATLEN    (HEXLEN + 3) /* x ' ... ' */
#define CHUNK     (4u << 20)

static char g_salt[MAX_DBS][33];
static char g_name[MAX_DBS][256];
static int  g_dbs = 0;

typedef struct { char key[65]; char salt[33]; int db; } key_t;
static key_t g_keys[MAX_KEYS];
static int   g_nkeys = 0;

static int hexval(int c){
    if(c>='0'&&c<='9') return c-'0';
    if(c>='a'&&c<='f') return c-'a'+10;
    if(c>='A'&&c<='F') return c-'A'+10;
    return -1;
}
static int is_hex(int c){ return hexval(c)>=0; }

static int read_salt(const char *p, char *out){
    FILE *f = fopen(p,"rb");
    if(!f) return -1;
    unsigned char h[16];
    if(fread(h,1,16,f)!=16){ fclose(f); return -1; }
    fclose(f);
    if(!memcmp(h,"SQLite format 3",15)) return -1;   /* already plaintext */
    for(int i=0;i<16;i++) sprintf(out+i*2,"%02x",h[i]);
    out[32]=0;
    return 0;
}

static int walk(const char *fpath,const struct stat *sb,int tf,struct FTW *fw){
    (void)sb;(void)fw;
    if(tf!=FTW_F) return 0;
    size_t n=strlen(fpath);
    if(n<3||strcmp(fpath+n-3,".db")) return 0;
    if(g_dbs>=MAX_DBS) return 0;
    char salt[33];
    if(read_salt(fpath,salt)) return 0;
    const char *rel=strstr(fpath,"db_storage/");
    rel = rel ? rel+11 : fpath;
    strncpy(g_salt[g_dbs],salt,32); g_salt[g_dbs][32]=0;
    strncpy(g_name[g_dbs],rel,255); g_name[g_dbs][255]=0;
    g_dbs++;
    return 0;
}

int main(int argc,char**argv){
    pid_t pid = argc>1 ? atoi(argv[1]) : -1;
    const char *out = argc>2 ? argv[2] : "keys.json";

    if(pid<=0){
        FILE *p=popen("pgrep -x WeChat","r");
        char b[32]; if(p&&fgets(b,sizeof b,p)) pid=atoi(b);
        if(p) pclose(p);
    }
    if(pid<=0){ fprintf(stderr,"WeChat not running\n"); return 1; }

    char base[512];
    const char *home=getenv("HOME");
    const char *su=getenv("SUDO_USER");
    if(su){ struct passwd *pw=getpwnam(su); if(pw) home=pw->pw_dir; }
    snprintf(base,sizeof base,
      "%s/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files",home);

    DIR *d=opendir(base);
    if(d){
        struct dirent *e;
        while((e=readdir(d))){
            if(e->d_name[0]=='.') continue;
            char sp[768]; struct stat st;
            snprintf(sp,sizeof sp,"%s/%s/db_storage",base,e->d_name);
            if(!stat(sp,&st)&&S_ISDIR(st.st_mode)) nftw(sp,walk,20,FTW_PHYS);
        }
        closedir(d);
    }
    fprintf(stderr,"pid=%d  encrypted DBs found=%d\n",pid,g_dbs);

    mach_port_t task;
    kern_return_t kr=task_for_pid(mach_task_self(),pid,&task);
    if(kr!=KERN_SUCCESS){
        fprintf(stderr,"task_for_pid failed kr=%d\n",kr);
        return 2;
    }

    mach_vm_address_t a=0; mach_vm_size_t sz; unsigned long long scanned=0; int rreg=0;
    while(1){
        mach_vm_size_t size=0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t ic=VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj;
        kr=mach_vm_region(task,&a,&size,VM_REGION_BASIC_INFO_64,
                          (vm_region_info_t)&info,&ic,&obj);
        if(kr!=KERN_SUCCESS) break;
        if(size==0){ a++; continue; }

        if(info.protection & VM_PROT_READ){
            rreg++;
            mach_vm_address_t ca=a;
            unsigned char *carry=NULL; size_t carrylen=0;   /* tail from prev chunk */
            while(ca<a+size){
                mach_vm_size_t cs=a+size-ca;
                if(cs>CHUNK) cs=CHUNK;
                vm_offset_t data; mach_msg_type_number_t dc;
                if(mach_vm_read(task,ca,cs,&data,&dc)==KERN_SUCCESS){
                    unsigned char *buf=(unsigned char*)data;
                    size_t total=dc;
                    unsigned char *win=NULL; size_t wlen=0;
                    if(carrylen){
                        wlen=carrylen+total;
                        win=malloc(wlen);
                        memcpy(win,carry,carrylen);
                        memcpy(win+carrylen,buf,total);
                    } else { win=buf; wlen=total; }

                    for(size_t i=0;i+PATLEN<=wlen;i++){
                        if(win[i]!='x'||win[i+1]!='\'') continue;
                        int ok=1;
                        for(int j=0;j<HEXLEN;j++) if(!is_hex(win[i+2+j])){ ok=0; break; }
                        if(!ok||win[i+2+HEXLEN]!='\'') continue;

                        char key[65],salt[33];
                        memcpy(key,win+i+2,64); key[64]=0;
                        memcpy(salt,win+i+2+64,32); salt[32]=0;
                        for(int j=0;j<64;j++) if(key[j]>='A'&&key[j]<='F') key[j]+=32;
                        for(int j=0;j<32;j++) if(salt[j]>='A'&&salt[j]<='F') salt[j]+=32;

                        int db=-1;
                        for(int k=0;k<g_dbs;k++) if(!strcmp(salt,g_salt[k])){ db=k; break; }
                        int dup=0;
                        for(int k=0;k<g_nkeys;k++)
                            if(!strcmp(g_keys[k].key,key)&&!strcmp(g_keys[k].salt,salt)){ dup=1; break; }
                        if(!dup&&g_nkeys<MAX_KEYS){
                            strcpy(g_keys[g_nkeys].key,key);
                            strcpy(g_keys[g_nkeys].salt,salt);
                            g_keys[g_nkeys].db=db;
                            g_nkeys++;
                        }
                    }
                    if(carrylen){ free(win); }
                    scanned+=dc;

                    free(carry); carry=NULL; carrylen=0;
                    if(total>PATLEN){
                        carrylen=PATLEN-1;
                        carry=malloc(carrylen);
                        memcpy(carry,buf+total-carrylen,carrylen);
                    }
                    mach_vm_deallocate(mach_task_self(),data,dc);
                }
                ca+=cs;
            }
            free(carry);
        }
        a+=size;
    }

    fprintf(stderr,"scanned %llu MB across %d readable regions, candidates=%d\n",
            scanned>>20,rreg,g_nkeys);

    int matched=0;
    for(int i=0;i<g_nkeys;i++) if(g_keys[i].db>=0) matched++;
    fprintf(stderr,"matched to DBs: %d/%d\n",matched,g_nkeys);

    FILE *fp=fopen(out,"w");
    if(!fp){ perror("open out"); return 3; }
    fprintf(fp,"{\n");
    int first=1, w=0;
    for(int i=0;i<g_nkeys;i++){
        if(g_keys[i].db<0) continue;
        fprintf(fp,"%s  \"%s\": {\"enc_key\": \"%s\"}",
                first?"":",\n", g_name[g_keys[i].db], g_keys[i].key);
        first=0; w++;
    }
    fprintf(fp,"\n}\n");
    fclose(fp);
    printf("wrote %d keys -> %s\n",w,out);
    for(int i=0;i<g_nkeys;i++)
        printf("  %-40s %s\n", g_keys[i].db>=0?g_name[g_keys[i].db]:"(unmatched)", g_keys[i].key);
    return w>0?0:4;
}
