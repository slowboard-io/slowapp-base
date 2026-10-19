"""Transport sealing for slowapp-remote (MANIFEST.md, "Remote runs", "Sealed runs").

The standard library has no AEAD, so this calls ChaCha20-Poly1305 (RFC 8439) in the libcrypto
that Python's own hashlib and ssl are built on, through ctypes: no new package in the base images.
If that can't be loaded, the `cryptography` package is used when it's installed; with neither,
sealing raises SealError and the wrapper refuses to run (it never falls back to plain text).

A sealed object is a STREAM (as in age): a header, then the plaintext in 64 KiB chunks, each
sealed on its own so a large /data never has to fit in memory, and truncation or reordering is
caught.

    header   = b"SBSEAL1\\n" || salt                      8 + 24 random bytes
    subkey   = HMAC-SHA256(key, b"slowapp-remote seal 1\\0" || label || b"\\0" || salt)
    chunk i  = ChaCha20-Poly1305(subkey, nonce_i, plaintext[i*65536 : (i+1)*65536], aad=header)
    nonce_i  = i as 11 bytes big-endian || (1 if chunk i is the last, else 0)

Every object has at least one chunk (an empty plaintext is one empty last chunk, 16 bytes of tag).
`label` is what the object is ("in", "out", "data", "log"), so one can't be swapped for another.
"""
import ctypes
import ctypes.util
import hashlib
import hmac
import os

MAGIC = b"SBSEAL1\n"
SALT = 24
HEADER = len(MAGIC) + SALT
CHUNK = 64 * 1024
TAG = 16
KEY = 32
LABELS = ("in", "out", "data", "log")

# EVP_CIPHER_CTX_ctrl codes (OpenSSL's evp.h; the same in 1.1 and 3.x)
_SET_IVLEN, _GET_TAG, _SET_TAG = 0x9, 0x10, 0x11


class SealError(Exception):
    """A sealed object that doesn't open (wrong key, wrong label, tampered, cut short), or no
    ChaCha20-Poly1305 to seal with."""


class _LibCrypto:
    """ChaCha20-Poly1305 from libcrypto, through ctypes."""

    name = "libcrypto"

    def __init__(self):
        lib = None
        for cand in self._candidates():
            try:
                lib = ctypes.CDLL(cand)
                lib.EVP_chacha20_poly1305          # noqa: B018 - the symbol must be there
                break
            except (OSError, AttributeError, TypeError):
                lib = None
        if lib is None:
            raise SealError("no libcrypto with ChaCha20-Poly1305")
        c, p, i = ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int
        lib.EVP_chacha20_poly1305.restype = p
        lib.EVP_chacha20_poly1305.argtypes = []
        lib.EVP_CIPHER_CTX_new.restype = p
        lib.EVP_CIPHER_CTX_new.argtypes = []
        lib.EVP_CIPHER_CTX_free.restype = None
        lib.EVP_CIPHER_CTX_free.argtypes = [p]
        lib.EVP_CipherInit_ex.restype = i
        lib.EVP_CipherInit_ex.argtypes = [p, p, p, c, c, i]
        lib.EVP_CIPHER_CTX_ctrl.restype = i
        lib.EVP_CIPHER_CTX_ctrl.argtypes = [p, i, i, p]
        lib.EVP_CipherUpdate.restype = i
        lib.EVP_CipherUpdate.argtypes = [p, p, ctypes.POINTER(i), c, i]
        lib.EVP_CipherFinal_ex.restype = i
        lib.EVP_CipherFinal_ex.argtypes = [p, p, ctypes.POINTER(i)]
        self.lib, self.cipher = lib, lib.EVP_chacha20_poly1305()
        lib.OpenSSL_version.restype = c
        lib.OpenSSL_version.argtypes = [i]
        try:
            self.name = f"libcrypto ({lib.OpenSSL_version(0).decode()})"
        except (AttributeError, UnicodeDecodeError):            # pragma: no cover
            pass

    @staticmethod
    def _candidates():
        # The libcrypto Python itself links: dlsym on _hashlib's handle also searches the
        # libraries it was linked with (Linux and macOS alike).
        try:
            import _hashlib
            if getattr(_hashlib, "__file__", None):
                yield _hashlib.__file__
        except ImportError:                                     # pragma: no cover
            pass
        yield from ("libcrypto.so.3", "libcrypto.so.1.1")
        found = ctypes.util.find_library("crypto")
        if found:
            yield found

    def _run(self, enc, key, nonce, data, aad, tag=None):
        lib = self.lib
        ctx = lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise MemoryError("EVP_CIPHER_CTX_new")
        try:
            n = ctypes.c_int(0)
            ok = (lib.EVP_CipherInit_ex(ctx, self.cipher, None, None, None, enc)
                  and lib.EVP_CIPHER_CTX_ctrl(ctx, _SET_IVLEN, len(nonce), None)
                  and lib.EVP_CipherInit_ex(ctx, None, None, key, nonce, enc))
            if ok and not enc:
                ok = lib.EVP_CIPHER_CTX_ctrl(ctx, _SET_TAG, TAG, ctypes.c_char_p(tag))
            if ok and aad:
                ok = lib.EVP_CipherUpdate(ctx, None, ctypes.byref(n), aad, len(aad))
            if not ok:
                raise SealError("libcrypto refused the ChaCha20-Poly1305 set-up")
            out = ctypes.create_string_buffer(len(data) + TAG)
            if not lib.EVP_CipherUpdate(ctx, out, ctypes.byref(n), data, len(data)):
                raise SealError("libcrypto refused the data")
            got = n.value
            if not lib.EVP_CipherFinal_ex(ctx, ctypes.cast(ctypes.byref(out, got), ctypes.c_void_p), ctypes.byref(n)):
                raise SealError("doesn't open: wrong key, or tampered with")
            got += n.value
            if enc:
                t = ctypes.create_string_buffer(TAG)
                if not lib.EVP_CIPHER_CTX_ctrl(ctx, _GET_TAG, TAG, ctypes.cast(t, ctypes.c_void_p)):
                    raise SealError("libcrypto gave no tag")
                return out.raw[:got] + t.raw
            return out.raw[:got]
        finally:
            lib.EVP_CIPHER_CTX_free(ctx)

    def encrypt(self, key, nonce, data, aad):
        return self._run(1, key, nonce, data, aad)

    def decrypt(self, key, nonce, data, aad):
        if len(data) < TAG:
            raise SealError("doesn't open: cut short")
        return self._run(0, key, nonce, data[:-TAG], aad, data[-TAG:])


class _Cryptography:
    """The same from the `cryptography` package, when libcrypto can't be reached through ctypes."""

    name = "cryptography"

    def __init__(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError as e:
            raise SealError(f"no cryptography package: {e}")
        self.aead = ChaCha20Poly1305

    def encrypt(self, key, nonce, data, aad):
        return self.aead(key).encrypt(nonce, data, aad)

    def decrypt(self, key, nonce, data, aad):
        from cryptography.exceptions import InvalidTag
        try:
            return self.aead(key).decrypt(nonce, data, aad)
        except InvalidTag:
            raise SealError("doesn't open: wrong key, or tampered with")


_aead = None


def aead():
    """The ChaCha20-Poly1305 in use (loaded once). SealError if there's none."""
    global _aead
    if _aead is None:
        errors = []
        for cls in (_LibCrypto, _Cryptography):
            try:
                _aead = cls()
                break
            except (SealError, OSError) as e:
                errors.append(f"{cls.name}: {e}")
        else:
            raise SealError("can't seal: " + "; ".join(errors))
    return _aead


def _subkey(key, label, salt):
    if label not in LABELS:
        raise ValueError(f"label {label!r}")
    return hmac.new(key, b"slowapp-remote seal 1\0" + label.encode() + b"\0" + salt, hashlib.sha256).digest()


def _nonce(i, last):
    return i.to_bytes(11, "big") + (b"\1" if last else b"\0")


def seal_stream(key, label, src, dst, salt=None):
    """Seal the readable file src into the writable file dst. Returns the bytes written."""
    if len(key) != KEY:
        raise SealError(f"a key is {KEY} bytes")
    a = aead()
    salt = os.urandom(SALT) if salt is None else salt
    header = MAGIC + salt
    sub = _subkey(key, label, salt)
    dst.write(header)
    written, i = len(header), 0
    chunk = src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK) if len(chunk) == CHUNK else b""
        last = not nxt
        ct = a.encrypt(sub, _nonce(i, last), chunk, header)
        dst.write(ct)
        written += len(ct)
        if last:
            return written
        chunk, i = nxt, i + 1


def open_stream(key, label, src, dst):
    """Open the sealed file src into dst. SealError (and dst holds a prefix) if it doesn't open."""
    if len(key) != KEY:
        raise SealError(f"a key is {KEY} bytes")
    a = aead()
    header = src.read(HEADER)
    if len(header) != HEADER or not header.startswith(MAGIC):
        raise SealError("not a sealed object")
    sub = _subkey(key, label, header[len(MAGIC):])
    i, n = 0, 0
    ct = src.read(CHUNK + TAG)
    while True:
        nxt = src.read(CHUNK + TAG) if len(ct) == CHUNK + TAG else b""
        last = not nxt
        pt = a.decrypt(sub, _nonce(i, last), ct, header)
        dst.write(pt)
        n += len(pt)
        if last:
            return n
        ct, i = nxt, i + 1


def seal_bytes(key, label, data):
    import io
    out = io.BytesIO()
    seal_stream(key, label, io.BytesIO(data), out)
    return out.getvalue()


def open_bytes(key, label, data):
    import io
    out = io.BytesIO()
    open_stream(key, label, io.BytesIO(data), out)
    return out.getvalue()


def seal_file(key, label, src, dst):
    with open(src, "rb") as s, open(dst, "wb") as d:
        return seal_stream(key, label, s, d)


def open_file(key, label, src, dst):
    with open(src, "rb") as s, open(dst, "wb") as d:
        return open_stream(key, label, s, d)
