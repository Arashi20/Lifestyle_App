import pytesseract
from flask import current_app
from PIL import Image, UnidentifiedImageError


class OCRUnavailableError(Exception):
    """Raised when the Tesseract OCR engine isn't installed/reachable."""


class InvalidImageError(Exception):
    """Raised when the upload isn't a readable image (or is absurdly large)."""


def extract_text_from_image(file_stream) -> str:
    """
    Run OCR on an uploaded ingredient-list photo and return the raw
    extracted text, for the user to review/edit before saving to
    Product.ingredients. Never trust this output as authoritative — small
    print, glossy packaging, and unusual INCI names make OCR error-prone.
    """
    tesseract_cmd = current_app.config.get("TESSERACT_CMD")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        image = Image.open(file_stream)
        # Pillow refuses "decompression bomb" images (tiny files that expand
        # to gigapixels) here rather than exhausting memory.
        image = image.convert("L")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise InvalidImageError("That file isn't a photo we can read — try a JPEG or PNG.") from exc
    try:
        return pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRUnavailableError(
            "Tesseract isn't installed on this machine (or TESSERACT_CMD is wrong). "
            "See CLAUDE.md for setup instructions."
        ) from exc
