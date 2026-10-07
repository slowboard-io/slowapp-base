"""The four inks, the ink check, PNG encoding for /out, and blob ids (docs/SLOWBOARD.md §4.3).

Index = panel code, the same order as epd/pack.py and renderer/halftone.py.
"""
import hashlib
import io
import struct

from PIL import Image

INKS = {"black": (0, 0, 0), "white": (255, 255, 255), "yellow": (255, 255, 0), "red": (255, 0, 0)}
PALETTE = list(INKS.values())
BLACK, WHITE, YELLOW, RED = PALETTE
INK_SETS = {"k4": PALETTE}          # the only ink set that ships (surface "452x444.k4")

MAX_BLOB = 256 * 1024               # each blob <= 256 KB encoded


class InkError(ValueError):
    pass


def check_inks(img, inks="k4"):
    """Raise InkError unless every pixel is one of the ink set's colours."""
    allowed = set(INK_SETS[inks])
    used = {c for _, c in img.convert("RGB").getcolors(maxcolors=1 << 24)}
    stray = used - allowed
    if stray:
        raise InkError(f"{len(stray)} colours are not inks, e.g. {sorted(stray)[:4]}")


def codes(img, inks="k4"):
    """Image in the inks -> bytes of panel codes, one per pixel. Off-palette pixels raise rather
    than being snapped, so a drawing mistake shows up in CI instead of as speckles on the appl."""
    check_inks(img, inks)
    pal = Image.new("P", (1, 1))
    pal.putpalette([v for c in INK_SETS[inks] for v in c])
    return img.convert("RGB").quantize(palette=pal, dither=Image.Dither.NONE)


def to_indexed(img, inks="k4"):
    """RGB image -> 'P' image whose palette is exactly the ink set (index = panel code)."""
    q = codes(img, inks)
    out = Image.frombytes("P", q.size, q.tobytes())
    out.putpalette([v for c in INK_SETS[inks] for v in c])
    return out


def encode_png(img, inks="k4"):
    """Indexed 2-bit PNG bytes: PLTE is exactly the ink set, no tRNS, no text chunks."""
    buf = io.BytesIO()
    to_indexed(img, inks).save(buf, "PNG", bits=2, optimize=False)
    data = buf.getvalue()
    if len(data) > MAX_BLOB:
        raise InkError(f"encoded card is {len(data)} bytes, over the {MAX_BLOB} byte limit")
    return data


def check_png(data, size=None, inks="k4"):
    """Validate PNG bytes against the bundle rules: bit depth 2 or 8, PLTE within the ink set, no
    tRNS, exact size. Returns the decoded RGB image."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise InkError("not a PNG")
    if len(data) > MAX_BLOB:
        raise InkError(f"{len(data)} bytes, over the {MAX_BLOB} byte limit")
    pos, depth, plte = 8, None, None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            depth, ctype = body[8], body[9]
            if ctype != 3:
                raise InkError(f"colour type {ctype}: cards must be indexed (3)")
            if depth not in (2, 8):
                raise InkError(f"bit depth {depth}: must be 2 or 8")
        elif kind == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            raise InkError("tRNS chunk: cards may not be transparent")
        pos += 12 + n
    if plte is None or not set(plte) <= set(INK_SETS[inks]):
        raise InkError(f"PLTE {plte} is not within the ink set")
    img = Image.open(io.BytesIO(data))
    img.load()
    if size and img.size != tuple(size):
        raise InkError(f"card is {img.size[0]}x{img.size[1]}, expected {size[0]}x{size[1]}")
    rgb = img.convert("RGB")
    check_inks(rgb, inks)
    return rgb


def pack_rows(img, inks="k4"):
    """Image -> packed rows, 4 px per byte, first pixel in the high bits (epd/pack.py)."""
    if img.width % 4:
        raise ValueError(f"width {img.width} isn't a multiple of 4")
    px = codes(img, inks).tobytes()
    out = bytearray(len(px) // 4)
    for i in range(4):
        sh = 6 - 2 * i
        for j, v in enumerate(px[i::4]):
            out[j] |= v << sh
    return bytes(out)


def blob_id(img, inks="k4"):
    """sha256("SBP2" || u16le w || u16le h || packed rows), hex. The hub computes the same id at
    ingest and slowbd recomputes it after decoding, so tests can pin pixels by id."""
    if isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(img))
    return hashlib.sha256(b"SBP2" + struct.pack("<HH", img.width, img.height) + pack_rows(img, inks)).hexdigest()
