/* keytest: brute-force 32-byte SQLCipher raw keys from a memory region by
   validating page-1 HMAC. usage: keytest <db> <region.bin> [alg] */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <CommonCrypto/CommonKeyDerivation.h>
#include <CommonCrypto/CommonHMAC.h>

int main(int argc,char**argv){
    if(argc<3){fprintf(stderr,"usage: %s db region.bin [sha512|sha256] [keysz]\n",argv[0]);return 1;}
    int ks = (argc>4)?atoi(argv[4]):32;
    int is512 = !(argc>3 && !strcmp(argv[3],"sha256"));
    int hmac_sz = is512?64:32, reserve = is512?80:48;
    unsigned char p1[4096];
    FILE*f=fopen(argv[1],"rb"); if(!f){perror("db");return 2;}
    if(fread(p1,1,4096,f)!=4096){fprintf(stderr,"short db\n");return 2;}
    fclose(f);
    unsigned char salt[16]; memcpy(salt,p1,16);
    unsigned char mac_salt[16]; for(int i=0;i<16;i++) mac_salt[i]=salt[i]^0x3a;
    size_t enc_len = 4096 - reserve + 16 - 16;   /* page1[16 .. 4096-reserve+16) */
    unsigned char msg[4200];
    memcpy(msg, p1+16, enc_len);
    unsigned int pgno=1; memcpy(msg+enc_len,&pgno,4);
    size_t msglen = enc_len+4;
    const unsigned char*stored = p1 + 4096 - hmac_sz;

    FILE*r=fopen(argv[2],"rb"); if(!r){perror("region");return 2;}
    fseek(r,0,SEEK_END); long rl=ftell(r); fseek(r,0,SEEK_SET);
    unsigned char*reg=malloc(rl); if(fread(reg,1,rl,r)!=(size_t)rl){fprintf(stderr,"short region\n");return 2;}
    fclose(r);

    printf("salt=%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x alg=%s reserve=%d region=%ld\n",
           salt[0],salt[1],salt[2],salt[3],salt[4],salt[5],salt[6],salt[7],
           salt[8],salt[9],salt[10],salt[11],salt[12],salt[13],salt[14],salt[15],
           is512?"sha512":"sha256", reserve, rl);
    int found=0;
    for(long off=0; off+ks<=rl; off++){
        unsigned char mk[32], out[64];
        if(CCKeyDerivationPBKDF(kCCPBKDF2, (const char*)reg+off, ks, mac_salt, 16,
                                is512?kCCPRFHmacAlgSHA512:kCCPRFHmacAlgSHA256, 2, mk, 32)!=0) continue;
        CCHmac(is512?kCCHmacAlgSHA512:kCCHmacAlgSHA256, mk, 32, msg, msglen, out);
        if(!memcmp(out, stored, hmac_sz)){
            printf("MATCH off=%ld key=", off);
            for(int i=0;i<ks;i++) printf("%02x", reg[off+i]);
            printf("\n"); found++;
        }
    }
    fprintf(stderr,"done, matches=%d\n",found);
    return found?0:3;
}
