import requests
from flask import current_app


def lookup_barcode(barcode: str):
    """
    Look up a product by barcode via the Open Beauty Facts API.
    Returns a dict with product info, or None if not found.
    Docs: https://world.openbeautyfacts.org/data
    """
    base = current_app.config["OPEN_BEAUTY_FACTS_API"]
    url = f"{base}/product/{barcode}.json"

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
    except requests.RequestException:
        return None

    data = response.json()
    if data.get("status") != 1:
        return None

    product = data.get("product", {})
    return {
        "name": product.get("product_name"),
        "brand": product.get("brands"),
        "ingredients": product.get("ingredients_text"),
        "image_url": product.get("image_url"),
    }
