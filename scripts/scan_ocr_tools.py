"""Public scan preprocessing/OCR tools. Receives image pixels, never truth records."""
from io import BytesIO
import os
from pathlib import Path
import subprocess
import time
import numpy as np
from PIL import Image, ImageOps, ImageFilter


def estimate_skew(image):
    """Maximize horizontal ink concentration using only raster pixels."""
    gray = image.convert('L'); gray.thumbnail((1000, 1300))
    # Body-only projection avoids the two-column header and page footer.
    gray = gray.crop((0, int(gray.height * .18), gray.width, int(gray.height * .85)))
    def score(angle):
        rotated = gray.rotate(angle, Image.Resampling.BILINEAR, fillcolor=255)
        ink = (np.asarray(rotated) < 150).sum(axis=1).astype('float64')
        return float(np.dot(ink, ink))
    coarse = [i / 2 for i in range(-4, 5)]
    best = max(coarse, key=score)
    candidates = [best + i / 8 for i in range(-2, 3)]
    angle = max(candidates, key=score)
    return 0. if abs(angle) < .2 else angle


def recognize(path):
    start = time.monotonic()
    with Image.open(path) as source:
        source.load(); image = source.convert('L'); angle = estimate_skew(image)
    if angle: image = image.rotate(angle, Image.Resampling.BICUBIC, fillcolor=255)
    # Remove only isolated dark single pixels. Keep connected punctuation/strokes.
    array = np.asarray(image).copy(); dark = array < 150
    padded = np.pad(dark.astype('uint8'), 1)
    counts = sum(padded[y:y+dark.shape[0], x:x+dark.shape[1]] for y in range(3) for x in range(3))
    array[dark & (counts == 1)] = 255
    image = Image.fromarray(array)
    background = np.asarray(image.filter(ImageFilter.GaussianBlur(max(10, image.width / 40)))).astype('float32')
    normalized = np.asarray(image).astype('float32') / np.maximum(background, 1) * 255
    image = ImageOps.autocontrast(Image.fromarray(np.clip(normalized, 0, 255).astype('uint8')), cutoff=.1)
    # Upsampling is a disclosed OCR preprocessing step, not source-dependent repair.
    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    stream = BytesIO(); image.save(stream, 'PNG')
    result = subprocess.run(['tesseract','stdin','stdout','--psm','6','-l','eng'], input=stream.getvalue(),
        capture_output=True, timeout=45, env={**os.environ, 'OMP_THREAD_LIMIT':'1'})
    return dict(text=result.stdout.decode('utf-8'), stderr=result.stderr.decode('utf-8'), exit_code=result.returncode,
                deskew_degrees=angle, elapsed_seconds=time.monotonic()-start)
