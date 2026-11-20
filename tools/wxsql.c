#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
int sqlite3_key(sqlite3*, const void*, int);
static int hex2bin(const char *h, unsigned char *o, int n){for(int i=0;i<n;i++){unsigned v;if(sscanf(h+2*i,"%2x",&v)!=1)return -1;o[i]=(unsigned char)v;}return 0;}
int main(int argc,char**argv){
    if(argc<3){fprintf(stderr,"usage: %s db keyhex [sql]\n",argv[0]);return 1;}
    unsigned char key[64]; int kl=strlen(argv[2])/2; if(hex2bin(argv[2],key,kl)){fprintf(stderr,"bad key\n");return 2;}
    sqlite3 *db=NULL; if(sqlite3_open(argv[1],&db)!=SQLITE_OK){fprintf(stderr,"open failed\n");return 3;}
    sqlite3_key(db,key,kl);
    const char *q = argc>3?argv[3]:"SELECT count(*) FROM sqlite_master";
    sqlite3_stmt *st=NULL; int rc=sqlite3_prepare_v2(db,q,-1,&st,NULL);
    if(rc!=SQLITE_OK){fprintf(stderr,"prepare rc=%d %s\n",rc,sqlite3_errmsg(db));return 4;}
    while((rc=sqlite3_step(st))==SQLITE_ROW){
        int n=sqlite3_column_count(st);
        for(int i=0;i<n;i++){const unsigned char*t=sqlite3_column_text(st,i);printf("%s%s",i?"|":"",t?(const char*)t:"NULL");}
        printf("\n");
    }
    if(rc!=SQLITE_DONE) fprintf(stderr,"step rc=%d %s\n",rc,sqlite3_errmsg(db));
    sqlite3_finalize(st); sqlite3_close(db); return 0;
}
