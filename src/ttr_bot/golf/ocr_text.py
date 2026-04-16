"""Optional OCR for golf course name detection (pytesseract + system tesseract)."""

import numpy as np

from ttr_bot.utils.logger import log


def read_text_from_bgr(crop_bgr: np.ndarray) -> str:
    """Return best-effort text from a BGR crop. Empty string if OCR unavailable."""
    if crop_bgr.size == 0:
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        rgb = crop_bgr[:, :, ::-1]
        pil = Image.fromarray(rgb)
        text = pytesseract.image_to_string(pil, config="--psm 6")
        return text or ""
    except Exception as exc:
        log.debug("Golf OCR skipped: %s", exc)
        return ""
