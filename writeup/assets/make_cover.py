"""Generate a dev.to-formatted cover image from the welcome-state screenshot.

dev.to expects a 1000x420 banner (2.4:1 ratio). Source screenshots vary in
dimensions across captures, so this script reduces the transform to: full
width crop + vertical center bias + LANCZOS resize. Manual cropping has been
imprecise; this is the reproducible path.

Run:
    .venv/bin/python writeup/assets/make_cover.py

If vertical placement is off, adjust VERTICAL_CENTER_BIAS (a fraction of the
image height where 0.5 = geometric center, lower = bias upward).
"""
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS = REPO_ROOT / "writeup" / "assets"
SOURCE = ASSETS / "welcome-state-2026-05-11.png"
OUTPUT = ASSETS / "cover-image.png"

TARGET_WIDTH = 1000
TARGET_HEIGHT = 420
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT  # 2.380...
# Welcome card sits slightly above geometric center because of bottom peach
# padding. 0.45 puts the crop center 5% above geometric center.
VERTICAL_CENTER_BIAS = 0.45


def main() -> int:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"source screenshot missing: {SOURCE}")

    with Image.open(SOURCE) as src:
        src_w, src_h = src.size
        print(f"input:  {SOURCE.name}  {src_w}x{src_h}")

        crop_h = round(src_w / TARGET_RATIO)
        if crop_h > src_h:
            raise ValueError(
                f"computed crop_h={crop_h} exceeds source height {src_h}; "
                f"source is too tall-thin for a {TARGET_RATIO:.3f}:1 full-width crop"
            )
        crop_center_y = round(VERTICAL_CENTER_BIAS * src_h)
        top = crop_center_y - crop_h // 2
        # Clamp so the crop box stays inside the image even if the bias pushes
        # the center near an edge.
        top = max(0, min(top, src_h - crop_h))
        bottom = top + crop_h
        crop_box = (0, top, src_w, bottom)
        print(f"crop:   left=0 top={top} right={src_w} bottom={bottom}")
        print(f"        size {src_w}x{crop_h}, ratio {src_w / crop_h:.3f}:1, bias {VERTICAL_CENTER_BIAS}")

        cropped = src.crop(crop_box).convert("RGB")
        resized = cropped.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)
        resized.save(OUTPUT, format="PNG")

    with Image.open(OUTPUT) as out:
        out_w, out_h = out.size
        print(f"output: {OUTPUT.name}  {out_w}x{out_h}")
        if (out_w, out_h) != (TARGET_WIDTH, TARGET_HEIGHT):
            raise RuntimeError(f"output dimensions {(out_w, out_h)} != target {(TARGET_WIDTH, TARGET_HEIGHT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
