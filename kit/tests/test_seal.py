"""Transport sealing (seal.py; MANIFEST.md, "Remote runs", "Sealed runs"): ChaCha20-Poly1305 from
libcrypto against RFC 8439's vector, the STREAM format's round trips at chunk edges, and that a
tampered, cut-short, reordered, relabelled or re-keyed object doesn't open.

  PYTHONPATH=kit python3 -m unittest discover -s kit/tests -p 'test_seal.py'
"""
import hashlib
import hmac
import io
import os
import unittest

from slowapp_kit import seal

KEY = bytes(range(32))


class Aead(unittest.TestCase):
    def test_rfc8439_vector(self):
        a = seal.aead()
        key = bytes(range(0x80, 0xa0))
        nonce = bytes.fromhex("070000004041424344454647")
        aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
        pt = (b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the "
              b"future, sunscreen would be it.")
        ct = a.encrypt(key, nonce, pt, aad)
        self.assertEqual(ct[:16].hex(), "d31a8d34648e60db7b86afbc53ef7ec2")
        self.assertEqual(ct[-16:].hex(), "1ae10b594f09e26a7e902ecbd0600691")
        self.assertEqual(a.decrypt(key, nonce, ct, aad), pt)
        with self.assertRaises(seal.SealError):
            a.decrypt(key, nonce, ct[:-1] + bytes([ct[-1] ^ 1]), aad)
        with self.assertRaises(seal.SealError):
            a.decrypt(key, nonce, ct, aad + b"x")

    def test_agrees_with_the_cryptography_package(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError:
            self.skipTest("cryptography isn't installed (it isn't in the base images)")
        a, n = seal.aead(), os.urandom(12)
        for size in (0, 1, 1000, 70000):
            pt = os.urandom(size)
            self.assertEqual(a.encrypt(KEY, n, pt, b"h"), ChaCha20Poly1305(KEY).encrypt(n, pt, b"h"))


class Stream(unittest.TestCase):
    def test_round_trips_at_the_chunk_edges(self):
        for size in (0, 1, seal.CHUNK - 1, seal.CHUNK, seal.CHUNK + 1, 3 * seal.CHUNK, 3 * seal.CHUNK + 7):
            with self.subTest(size=size):
                pt = os.urandom(size)
                sealed = seal.seal_bytes(KEY, "out", pt)
                chunks = max(1, -(-size // seal.CHUNK))
                self.assertEqual(len(sealed), seal.HEADER + size + chunks * seal.TAG)
                self.assertEqual(seal.open_bytes(KEY, "out", sealed), pt)

    def test_the_format_is_what_the_manifest_says(self):
        """Built by hand from MANIFEST.md's description, so the hub's implementation has a check."""
        salt, pt = bytes(24), b"x" * (seal.CHUNK + 5)
        out = io.BytesIO()
        seal.seal_stream(KEY, "data", io.BytesIO(pt), out, salt=salt)
        header = b"SBSEAL1\n" + salt
        sub = hmac.new(KEY, b"slowapp-remote seal 1\0data\0" + salt, hashlib.sha256).digest()
        a = seal.aead()
        want = (header + a.encrypt(sub, (0).to_bytes(11, "big") + b"\0", pt[:seal.CHUNK], header)
                + a.encrypt(sub, (1).to_bytes(11, "big") + b"\1", pt[seal.CHUNK:], header))
        self.assertEqual(out.getvalue(), want)

    def test_what_doesnt_open(self):
        pt = os.urandom(2 * seal.CHUNK + 10)
        s = seal.seal_bytes(KEY, "in", pt)
        c = seal.CHUNK + seal.TAG
        first, second, last = (s[seal.HEADER:seal.HEADER + c], s[seal.HEADER + c:seal.HEADER + 2 * c],
                               s[seal.HEADER + 2 * c:])
        bad = {
            "a flipped byte": s[:100] + bytes([s[100] ^ 1]) + s[101:],
            "a flipped header byte": s[:10] + bytes([s[10] ^ 1]) + s[11:],
            "the last chunk dropped": s[:seal.HEADER + 2 * c],
            "cut inside a chunk": s[:-5],
            "chunks swapped": s[:seal.HEADER] + second + first + last,
            "header only": s[:seal.HEADER],
            "not sealed": b"plain text, not sealed at all" * 10,
        }
        for why, body in bad.items():
            with self.subTest(why):
                with self.assertRaises(seal.SealError):
                    seal.open_bytes(KEY, "in", body)
        with self.assertRaises(seal.SealError):
            seal.open_bytes(KEY, "out", s)                     # another label
        with self.assertRaises(seal.SealError):
            seal.open_bytes(os.urandom(32), "in", s)           # another key
        with self.assertRaises(seal.SealError):
            seal.seal_bytes(b"short", "in", b"")
        with self.assertRaises(ValueError):
            seal.seal_bytes(KEY, "other", b"")

    def test_same_plaintext_seals_differently(self):
        self.assertNotEqual(seal.seal_bytes(KEY, "log", b"hi"), seal.seal_bytes(KEY, "log", b"hi"))

    def test_files(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        (d / "a").write_bytes(b"abc" * 30000)
        seal.seal_file(KEY, "data", d / "a", d / "a.sealed")
        seal.open_file(KEY, "data", d / "a.sealed", d / "b")
        self.assertEqual((d / "b").read_bytes(), b"abc" * 30000)


if __name__ == "__main__":
    unittest.main()
