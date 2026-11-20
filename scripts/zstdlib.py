import ctypes, ctypes.util
_lib = ctypes.CDLL("/opt/homebrew/lib/libzstd.1.dylib")
_lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
_lib.ZSTD_getFrameContentSize.argtypes=[ctypes.c_char_p, ctypes.c_size_t]
_lib.ZSTD_decompress.restype = ctypes.c_size_t
_lib.ZSTD_decompress.argtypes=[ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
_lib.ZSTD_isError.restype = ctypes.c_uint
_lib.ZSTD_isError.argtypes=[ctypes.c_size_t]
def decompress(b):
    if not b: return b""
    b = bytes(b)
    if not b.startswith(b"\x28\xb5\x2f\xfd"): return b
    sz = _lib.ZSTD_getFrameContentSize(b, len(b))
    if sz >= 2**63: return b""
    out = ctypes.create_string_buffer(sz)
    n = _lib.ZSTD_decompress(out, sz, b, len(b))
    if _lib.ZSTD_isError(n): return b""
    return out.raw[:n]
