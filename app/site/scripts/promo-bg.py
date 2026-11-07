"""Slow, muted flowing colour for the promo video's backdrop.

    python promo-bg.py out.mp4 seconds [fps]

Soft colour fields drift on long orbits (periods 60-100 s); each pixel is a
weighted mix of a pale base and the fields, so colours stay inside the
palette. Rendered small (the fields are huge and soft) and upscaled by
promo.mjs, which adds a little grain against banding.
"""
import subprocess
import sys

import numpy as np

W, H = 384, 216
BASE = np.array([0xEC, 0xEA, 0xF0], float)
# colour, period s, phase, centre, orbit, radius (fraction of W)
FIELDS = [
    ((0xB3, 0xAA, 0xDE), 71, 0.0, (0.26, 0.30), (0.16, 0.14), 0.24),  # lavender
    ((0xA3, 0xC3, 0xE6), 83, 2.1, (0.74, 0.26), (0.18, 0.12), 0.24),  # dusty blue
    ((0xAC, 0xD6, 0xC9), 97, 4.2, (0.36, 0.76), (0.14, 0.16), 0.22),  # sage
    ((0xF0, 0xC6, 0xB4), 64, 1.0, (0.76, 0.72), (0.16, 0.14), 0.22),  # peach
]
W0 = 0.18  # weight of the base everywhere

out, secs = sys.argv[1], float(sys.argv[2])
fps = int(sys.argv[3]) if len(sys.argv) > 3 else 30
ff = subprocess.Popen(
    ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
     "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "6",
     "-pix_fmt", "yuv444p", out],
    stdin=subprocess.PIPE,
)
y, x = np.mgrid[0:H, 0:W].astype(float)
for n in range(int(secs * fps) + 1):
    t = n / fps
    acc = BASE[None, None, :] * W0
    wsum = np.full((H, W), W0)
    for col, T, ph, (cx, cy), (ax, ay), r in FIELDS:
        px = W * (cx + ax * np.sin(2 * np.pi * t / T + ph))
        py = H * (cy + ay * np.cos(2 * np.pi * t / (T * 1.3) + ph))
        w = np.exp(-((x - px) ** 2 + (y - py) ** 2) / (2 * (r * W) ** 2))
        acc = acc + w[..., None] * np.array(col, float)
        wsum += w
    ff.stdin.write(np.clip(acc / wsum[..., None], 0, 255).astype(np.uint8).tobytes())
ff.stdin.close()
ff.wait()
