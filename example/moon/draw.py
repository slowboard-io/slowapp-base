"""Moon cards in the panel's inks: black, white, yellow, red. Text is drawn without antialiasing
(fontmode "1"), because every pixel must be one of the inks."""
import math

from PIL import ImageDraw

import slowapp_kit as kit
from slowapp_kit import BLACK, RED, WHITE, YELLOW

from . import phase


def disc(d, cx, cy, r, t, south=False):
    """The moon at time t: lit part yellow, dark part black, outline black."""
    a = phase.age(t) / phase.SYNODIC_DAYS            # 0 new, 0.5 full
    waxing = a < 0.5
    k = math.cos(2 * math.pi * a)                    # terminator: x = k * half-width, 1 new .. -1 full
    lit_right = waxing != south                      # northern sky: waxing is lit on the right
    for dy in range(-r, r + 1):
        half = int(math.sqrt(max(r * r - dy * dy, 0)))
        if half == 0:
            continue
        term = int(round(k * half))
        x0, x1 = cx - half, cx + half
        # Lit span: from the terminator to the lit limb.
        if lit_right:
            lx0, lx1 = cx + term, x1
        else:
            lx0, lx1 = x0, cx - term
        d.line((x0, cy + dy, x1, cy + dy), fill=BLACK)
        if lx1 > lx0:
            d.line((lx0, cy + dy, lx1, cy + dy), fill=YELLOW)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=BLACK, width=2)


def home(ctx, surface, south):
    t = ctx.for_
    img = ctx.canvas(surface)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    w, h = img.size
    d.text((w // 2, 18), phase.name(t), font=kit.font("DejaVuSans-Bold.ttf", 34), fill=BLACK, anchor="mt")
    disc(d, w // 2, 200, 120, t, south)
    small = kit.font("DejaVuSans.ttf", 22)
    d.text((w // 2, 338), f"{phase.illumination(t) * 100:.0f}% lit, day {phase.age(t):.1f}",
           font=small, fill=BLACK, anchor="mt")
    full, new = phase.next_phase(t, 0.5), phase.next_phase(t, 0.0)
    d.text((w // 2, 374), f"Full {full:%a %d %b}", font=small, fill=RED, anchor="mt")
    d.text((w // 2, 404), f"New {new:%a %d %b}", font=small, fill=BLACK, anchor="mt")
    return img


def week(ctx, surface, south):
    """The next eight days, two rows of four."""
    from datetime import timedelta
    img = ctx.canvas(surface)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    w, h = img.size
    d.text((w // 2, 14), "The week ahead", font=kit.font("DejaVuSans-Bold.ttf", 28), fill=BLACK, anchor="mt")
    label = kit.font("DejaVuSans.ttf", 18)
    cw = w // 4
    for i in range(8):
        t = ctx.for_ + timedelta(days=i)
        cx, cy = cw * (i % 4) + cw // 2, 140 + (i // 4) * 180
        disc(d, cx, cy, 44, t, south)
        d.text((cx, cy + 56), f"{t:%a %d}", font=label, fill=RED if i == 0 else BLACK, anchor="mt")
    return img
