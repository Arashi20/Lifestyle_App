import re

import requests
from flask import current_app

# EAN/UPC product barcodes are all digits. Anything else (a scanned QR code's
# text, say) must not be spliced into the API URL path.
BARCODE_RE = re.compile(r"^\d{6,14}$")


def lookup_barcode(barcode: str):
    """
    Look up a product by barcode via the Open Beauty Facts API.
    Returns a dict with product info, or None if not found.
    Docs: https://world.openbeautyfacts.org/data
    """
    if not BARCODE_RE.match(barcode or ""):
        return None

    base = current_app.config["OPEN_BEAUTY_FACTS_API"]
    url = f"{base}/product/{barcode}.json"

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        data = response.json()
    except ValueError:
        return None
    if data.get("status") != 1:
        return None

    product = data.get("product", {})
    return {
        "name": product.get("product_name"),
        "brand": product.get("brands"),
        "ingredients": product.get("ingredients_text"),
        "image_url": product.get("image_url"),
    }
