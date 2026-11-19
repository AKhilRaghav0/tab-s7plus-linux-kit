#!/usr/bin/env python3
"""Build an Xcursor theme 'spen-dot': a small Samsung-style hover ring instead of arrows."""
import os, struct, sys
from PIL import Image, ImageDraw

OUT = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/.local/share/icons/spen-dot")
SIZES = [24, 32, 48, 64, 96]


def ring(px):
    s = 4  # supersample
    im = Image.new("RGBA", (px * s, px * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = px * s / 2
    r = px * s * 0.26           # ring radius
    w = max(2, int(px * s * 0.045))
    # thin white ring with a hairline dark edge on both sides (visible on light and dark), faint fill
    d.ellipse([c - r, c - r, c + r, c + r], fill=(255, 255, 255, 40))
    d.ellipse([c - r - s, c - r - s, c + r + s, c + r + s], outline=(0, 0, 0, 120), width=w + 2 * s)
    d.ellipse([c - r, c - r, c + r, c + r], outline=(255, 255, 255, 240), width=w)
    return im.resize((px, px), Image.LANCZOS)


def xcursor(images):
    """images: list of (nominal_size, PIL RGBA) -> Xcursor bytes (ARGB premultiplied)."""
    ntoc = len(images)
    header = struct.pack("<4sIII", b"Xcur", 16, 0x10000, ntoc)
    toc, chunks, pos = b"", b"", 16 + ntoc * 12
    for size, im in images:
        w, h = im.size
        px = bytearray()
        for r, g, b, a in (im.get_flattened_data() if hasattr(im, 'get_flattened_data') else im.getdata()):
            px += struct.pack("<BBBB", b * a // 255, g * a // 255, r * a // 255, a)   # BGRA premultiplied = ARGB LE
        chunk = struct.pack("<IIIIIIIII", 36, 0xFFFD0002, size, 1, w, h, w // 2, h // 2, 0) + bytes(px)
        toc += struct.pack("<III", 0xFFFD0002, size, pos)
        chunks += chunk
        pos += len(chunk)
    return header + toc + chunks


os.makedirs(os.path.join(OUT, "cursors"), exist_ok=True)
data = xcursor([(s, ring(s)) for s in SIZES])
main = os.path.join(OUT, "cursors", "default")
open(main, "wb").write(data)
names = ["left_ptr", "arrow", "top_left_arrow", "pointer", "hand1", "hand2", "pointing_hand", "text", "xterm",
         "ibeam", "crosshair", "cross", "grab", "grabbing", "openhand", "closedhand", "move", "fleur", "all-scroll",
         "context-menu", "help", "progress", "wait", "watch", "left_ptr_watch", "cell", "copy", "alias",
         "no-drop", "not-allowed", "default-ptr"]
for n in names:
    p = os.path.join(OUT, "cursors", n)
    if os.path.lexists(p):
        os.remove(p)
    os.symlink("default", p)
open(os.path.join(OUT, "index.theme"), "w").write("[Icon Theme]\nName=S Pen dot\nComment=Samsung-style hover ring\nInherits=Adwaita\n")
ring(256).save(os.path.join(OUT, "preview.png"))
print("theme written to", OUT)
