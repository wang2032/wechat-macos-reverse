#include <stdio.h>
#include <string.h>
#include <sqlite3.h>
int sqlite3_key(sqlite3*, const void*, int);
static int h2b(const char*h,unsigned char*o,int n){for(int i=0;i<n;i++){unsigned v;if(sscanf(h+2*i,"%2x",&v)!=1)return -1;o[i]=(unsigned char)v;}return 0;}
int main(int c,char**v){
  if(c<4){fprintf(stderr,"usage: %s in.db keyhex out.db\n",v[0]);return 1;}
  unsigned char k[64]; int kl=strlen(v[2])/2; h2b(v[2],k,kl);
  sqlite3 *db=0; sqlite3_open(v[1],&db); sqlite3_key(db,k,kl);
  char *e=0; int rc; char sql[2048];
  rc=sqlite3_exec(db,"SELECT count(*) FROM sqlite_master",0,0,&e);
  printf("key rc=%d ext=%d %s\n",rc,sqlite3_extended_errcode(db),e?e:"ok"); e=0;
  snprintf(sql,sizeof sql,"ATTACH DATABASE '%s' AS p KEY ''",v[3]);
  rc=sqlite3_exec(db,sql,0,0,&e);
  printf("attach rc=%d ext=%d %s\n",rc,sqlite3_extended_errcode(db),e?e:"ok"); e=0;
  if(rc==0){ rc=sqlite3_exec(db,"SELECT sqlcipher_export('p')",0,0,&e); printf("export rc=%d %s\n",rc,e?e:"ok"); }
  return rc;
}
