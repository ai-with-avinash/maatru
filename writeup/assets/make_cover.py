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
# Bias the vertical crop slightly below geometric center to keep the మా
# anchor inside the top edge of the cover and push the Start button cleanly
# off the bottom edge. 0.55 puts the crop center 5% below geometric center.
VERTICAL_CENTER_BIAS = 0.55
# Welcome card sits right of geometric center on the desktop layout (the
# container max-width:480px + auto margin places it ~65% across a wide
# viewport screenshot). 0.65 anchors the horizontal crop on the card.
HORIZONTAL_CENTER_BIAS = 0.65
# Zoom: how much of the source's width to keep before upsampling to TARGET_WIDTH.
# ZOOM=1.0 keeps full width (no horizontal crop). ZOOM=1.3 keeps ~77% of the
# width, centered per HORIZONTAL_CENTER_BIAS, making the card fill more of the
# final cover. Vertical crop scales together so the 2.4:1 aspect is preserved.
ZOOM = 1.3


def main() -> int:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"source screenshot missing: {SOURCE}")

    with Image.open(SOURCE) as src:
        src_w, src_h = src.size
        print(f"input:  {SOURCE.name}  {src_w}x{src_h}")

        # Compute crop window. ZOOM controls how much of the source to keep
        # before upsampling to (TARGET_WIDTH, TARGET_HEIGHT). The crop window
        # always carries the target 2.4:1 ratio so the resize is a uniform scale.
        if ZOOM < 1.0:
            raise ValueError(f"ZOOM must be >= 1.0; got {ZOOM}")
        crop_w = round(src_w / ZOOM)
        crop_h = round(crop_w / TARGET_RATIO)
        if crop_h > src_h:
            # Source is too short for this ZOOM at the target ratio — fall back
            # to height-bound: derive crop_w from src_h instead.
            crop_h = src_h
            crop_w = round(crop_h * TARGET_RATIO)
            crop_w = min(crop_w, src_w)

        crop_center_x = round(HORIZONTAL_CENTER_BIAS * src_w)
        crop_center_y = round(VERTICAL_CENTER_BIAS * src_h)
        left = crop_center_x - crop_w // 2
        top = crop_center_y - crop_h // 2
        # Clamp so the crop box stays inside the image.
        left = max(0, min(left, src_w - crop_w))
        top = max(0, min(top, src_h - crop_h))
        right = left + crop_w
        bottom = top + crop_h

        crop_box = (left, top, right, bottom)
        print(f"crop:   left={left} top={top} right={right} bottom={bottom}")
        print(f"        size {crop_w}x{crop_h}, ratio {crop_w / crop_h:.3f}:1")
        print(f"        zoom={ZOOM}, h_bias={HORIZONTAL_CENTER_BIAS}, v_bias={VERTICAL_CENTER_BIAS}")

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
