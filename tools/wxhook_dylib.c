/* wxhook.dylib: interpose CCKeyDerivationPBKDF inside WeChat and log args. */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <CommonCrypto/CommonKeyDerivation.h>

static FILE *g_log;

static void lg(const char *s) {
    if (!g_log) {
        g_log = fopen("/tmp/wxkeys.log", "a");
        if (!g_log) g_log = stderr;
    }
    fputs(s, g_log);
    fflush(g_log);
}

static void hexcat(char *out, const unsigned char *b, size_t n) {
    static const char *d = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) { out[2*i] = d[b[i] >> 4]; out[2*i+1] = d[b[i] & 15]; }
    out[2*n] = 0;
}

int my_pbkdf(CCPBKDFAlgorithm algorithm,
             const char *password, size_t passwordLen,
             const uint8_t *salt, size_t saltLen,
             CCPseudoRandomAlgorithm prf, unsigned rounds,
             uint8_t *derivedKey, size_t derivedKeyLen);

static const struct { const void *replacement; const void *replacee; } interposers[]
    __attribute__((section("__DATA,__interpose"))) __attribute__((used)) = {
    { (const void *)my_pbkdf, (const void *)CCKeyDerivationPBKDF },
};

int my_pbkdf(CCPBKDFAlgorithm algorithm,
             const char *password, size_t passwordLen,
             const uint8_t *salt, size_t saltLen,
             CCPseudoRandomAlgorithm prf, unsigned rounds,
             uint8_t *derivedKey, size_t derivedKeyLen) {
    typedef int (*fn_t)(CCPBKDFAlgorithm, const char*, size_t, const uint8_t*, size_t,
                        CCPseudoRandomAlgorithm, unsigned, uint8_t*, size_t);
    fn_t real = (fn_t)interposers[0].replacee;
    int r = real(algorithm, password, passwordLen, salt, saltLen, prf, rounds, derivedKey, derivedKeyLen);

    char buf[4096];
    static char h1[4096], h2[4096];
    size_t n1 = passwordLen < 512 ? passwordLen : 512;
    size_t n2 = saltLen < 256 ? saltLen : 256;
    size_t n3 = derivedKeyLen < 512 ? derivedKeyLen : 512;
    hexcat(h1, (const unsigned char*)password, n1);
    hexcat(h2, salt, n2);
    int off = snprintf(buf, sizeof buf,
        "PBKDF2 alg=%d pwlen=%zu saltlen=%zu prf=%u rounds=%u ret=%d caller=%p\n  pw=%s\n  salt=%s\n",
        (int)algorithm, passwordLen, saltLen, (unsigned)prf, rounds, r, __builtin_return_address(0), h1, h2);
    char h3[1100];
    hexcat(h3, derivedKey, n3);
    snprintf(buf + off, sizeof buf - off, "  dk=%s\n", h3);
    lg(buf);
    return r;
}

__attribute__((constructor)) static void init(void) {
    char b[256];
    snprintf(b, sizeof b, "== wxhook loaded pid=%d ==\n", (int)getpid());
    lg(b);
}
