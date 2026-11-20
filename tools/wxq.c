#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sqlite3.h>
int sqlite3_key(sqlite3*, const void*, int);
static int hex2bin(const char*h,unsigned char*o,int n){for(int i=0;i<n;i++){unsigned v;if(sscanf(h+2*i,"%2x",&v)!=1)return -1;o[i]=(unsigned char)v;}return 0;}
static void esc(const unsigned char*s,int n){ if(!s){printf("\\N");return;} for(int i=0;i<n;i++){unsigned char c=s[i]; if(c=='\t')printf("\\t"); else if(c=='\n')printf("\\n"); else if(c=='\r')printf("\\r"); else if(c=='\\')printf("\\\\"); else putchar(c);} }
int main(int argc,char**argv){
    if(argc<4){fprintf(stderr,"usage: %s db keyhex sql\n",argv[0]);return 1;}
    unsigned char key[64]; int kl=strlen(argv[2])/2; if(kl>32||hex2bin(argv[2],key,kl)){fprintf(stderr,"bad key\n");return 2;}
    /* 只读打开：库文件连写权限都不申请，任何写语句都会失败 */
    const char *q=argv[3]; while(*q==' '||*q=='\n'||*q=='\t')q++;
    if(strncasecmp(q,"select",6)!=0){fprintf(stderr,"readonly: only SELECT is allowed\n");return 6;}
    sqlite3 *db=NULL; if(sqlite3_open_v2(argv[1],&db,SQLITE_OPEN_READONLY,NULL)!=SQLITE_OK){fprintf(stderr,"open: %s\n",sqlite3_errmsg(db));return 3;}
    sqlite3_key(db,key,kl);
    sqlite3_stmt *st=NULL; int rc=sqlite3_prepare_v2(db,argv[3],-1,&st,NULL);
    if(rc!=SQLITE_OK){fprintf(stderr,"prepare rc=%d %s\n",rc,sqlite3_errmsg(db));return 4;}
    while((rc=sqlite3_step(st))==SQLITE_ROW){
        int n=sqlite3_column_count(st);
        for(int i=0;i<n;i++){ if(i)putchar('\t');
            if(sqlite3_column_type(st,i)==SQLITE_BLOB){ const unsigned char*b=sqlite3_column_blob(st,i); int len=sqlite3_column_bytes(st,i); printf("0x"); for(int j=0;j<len;j++)printf("%02x",b[j]); }
            else { const unsigned char*t=sqlite3_column_text(st,i); esc(t, sqlite3_column_bytes(st,i)); } }
        putchar('\n');
    }
    if(rc!=SQLITE_DONE){fprintf(stderr,"step rc=%d %s\n",rc,sqlite3_errmsg(db));return 5;}
    sqlite3_finalize(st); sqlite3_close(db); return 0;
}
