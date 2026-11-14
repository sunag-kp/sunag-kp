"""Consistent colour grading + intentional crops for portfolio photography.

Two grades, one per design direction:
  night  - desaturated, teal-tamed, tungsten-warm highlights, crushed blacks
  tie    - warm monochrome that holds only saturated reds (the tie)

Usage: python3 tools/grade.py <jobs.json> <out_dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent


def rgb_to_hsv(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(-1)
    mn = a.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rc = np.where(m, (mx - r) / np.where(m, d, 1), 0)
    gc = np.where(m, (mx - g) / np.where(m, d, 1), 0)
    bc = np.where(m, (mx - b) / np.where(m, d, 1), 0)
    h = np.where(mx == r, bc - gc, np.where(mx == g, 2.0 + rc - bc, 4.0 + gc - rc))
    h = (h / 6.0) % 1.0
    h = np.where(m, h, 0)
    s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    i = np.floor(h * 6.0).astype(int) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    choices = [
        (v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q),
    ]
    out = np.zeros(h.shape + (3,), dtype=np.float32)
    for k, (r, g, b) in enumerate(choices):
        m = i == k
        out[..., 0] = np.where(m, r, out[..., 0])
        out[..., 1] = np.where(m, g, out[..., 1])
        out[..., 2] = np.where(m, b, out[..., 2])
    return out


def luma(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def s_curve(x, k):
    """Blend between identity and smoothstep. k in 0..1."""
    x = np.clip(x, 0, 1)
    return x * (1 - k) + (x * x * (3 - 2 * x)) * k


def vignette(a, strength, cx=0.5, cy=0.5):
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = (xx / w - cx) * 2
    dy = (yy / h - cy) * 2
    r = np.sqrt(dx * dx + dy * dy) / 1.4142
    v = 1 - strength * np.clip(r, 0, 1) ** 2.2
    return a * v[..., None]


def grade_night(a, exposure=1.0, gamma=1.0):
    h, s, v = rgb_to_hsv(a)
    # hue-dependent saturation: tame teal/green, keep skin
    hue_pts = np.array([0, 20, 45, 70, 110, 160, 200, 250, 300, 340, 360]) / 360.0
    sat_k = np.array([.82, .86, .70, .40, .30, .26, .30, .34, .45, .70, .82])
    k = np.interp(h, hue_pts, sat_k)
    s = np.clip(s * k, 0, 1)
    # pull cyan-green slightly toward a deeper, bluer teal
    teal = np.exp(-(((h - 0.47) / 0.09) ** 2))
    h = (h + teal * 0.035) % 1.0
    a = hsv_to_rgb(h, s, v)
    a = np.clip(a * exposure, 0, 1) ** gamma
    a = s_curve(a, 0.55)
    l = luma(a)[..., None]
    shadow = np.array([-0.012, 0.004, 0.016], dtype=np.float32)
    high = np.array([0.050, 0.014, -0.045], dtype=np.float32)
    a = a + shadow * (1 - l) ** 2 + high * l ** 1.5
    a = np.clip(a, 0, 1)
    a = a * 0.94 + 0.012  # sit blacks just above pure black, never clip
    return a


def grade_tie(a, exposure=1.0, gamma=1.0, hold=1.0):
    h, s, v = rgb_to_hsv(a)
    # mask: saturated reds only (the tie), not skin
    hd = np.minimum(np.abs(h - 0.985), 1 - np.abs(h - 0.985)) * 360  # distance to 355deg
    m_h = np.clip((22 - hd) / 9.0, 0, 1)
    m_s = np.clip((s - 0.62) / 0.14, 0, 1)
    m_v = np.clip((v - 0.16) / 0.12, 0, 1)
    m = (m_h * m_s * m_v * hold)[..., None]

    b = np.clip(a * exposure, 0, 1) ** gamma
    l = s_curve(luma(b), 0.6)[..., None]
    lo = np.array([0.030, 0.026, 0.024], dtype=np.float32)
    hi = np.array([0.955, 0.915, 0.850], dtype=np.float32)
    mono = lo + (hi - lo) * l
    # faint trace of original chroma so skin does not go dead
    trace = s_curve(b, 0.5)
    mono = mono * 0.90 + trace * 0.10
    # held red, nudged toward vermilion
    hr = (h + 0.012) % 1.0
    red = hsv_to_rgb(hr, np.clip(s * 0.96, 0, 1), np.clip(v * exposure, 0, 1) ** gamma)
    red = s_curve(red, 0.5)
    out = mono * (1 - m) + red * m
    return np.clip(out, 0, 1)


GRADES = {"night": grade_night, "tie": grade_tie}


def run(job, out_dir):
    src = ROOT / job["src"]
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    W, H = im.size
    x0, y0, x1, y1 = job.get("crop", [0, 0, 1, 1])
    box = (round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H))
    im = im.crop(box)
    if job.get("flip"):
        im = ImageOps.mirror(im)
    # grade at (at most) 2x target for speed, then resize
    widths = job["widths"]
    big = max(widths)
    if im.width > big * 1.5:
        im = im.resize((round(big * 1.5), round(im.height * big * 1.5 / im.width)), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32) / 255.0
    g = GRADES[job["grade"]]
    a = g(a, **job.get("params", {}))
    vg = job.get("vignette", 0.0)
    if vg:
        a = vignette(a, vg, *job.get("vcenter", [0.5, 0.5]))
    graded = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
    for w in widths:
        if w > graded.width:
            w = graded.width
        hh = round(graded.height * w / graded.width)
        out = graded.resize((w, hh), Image.LANCZOS)
        q = job.get("quality", 74)
        p = out_dir / f"{job['name']}-{w}.webp"
        while True:
            out.save(p, "WEBP", quality=q, method=6)
            if p.stat().st_size <= 300_000 or q <= 40:
                break
            q -= 6
        print(f"{p.name:44s} {out.width}x{out.height}  q{q}  {p.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    jobs = json.loads(Path(sys.argv[1]).read_text())
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for j in jobs:
        run(j, out_dir)
