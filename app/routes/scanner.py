from flask import Blueprint, render_template, redirect, request, flash, session, url_for

from app import db
from app.models import Product
from app.services.openbeautyfacts import lookup_barcode
from app.services.ocr import extract_text_from_image, OCRUnavailableError

scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")


@scanner_bp.route("/")
def scanner_page():
    return render_template("scanner.html")


@scanner_bp.route("/result/<barcode>")
def scan_result(barcode):
    """Landed on after barcode.js decodes a barcode client-side."""
    result = lookup_barcode(barcode)
    return render_template("scanner_result.html", barcode=barcode, result=result)


@scanner_bp.route("/save", methods=["POST"])
def save_scanned_product():
    product = Product(
        name=request.form.get("name") or "Unknown product",
        brand=request.form.get("brand"),
        ingredients=request.form.get("ingredients"),
        barcode=request.form.get("barcode"),
    )
    db.session.add(product)
    db.session.commit()
    flash(f'"{product.name}" saved.', "success")
    return redirect(url_for("products.view_product", product_id=product.id))


@scanner_bp.route("/ocr", methods=["GET", "POST"])
def ocr_scan():
    """Fallback for when a product isn't found in Open Beauty Facts (or
    barcode scanning isn't an option): photograph the ingredients list and
    extract the text instead."""
    if request.method == "POST":
        photo = request.files.get("photo")
        if not photo or not photo.filename:
            return render_template("scanner_ocr.html", error="No photo selected.")
        try:
            extracted_text = extract_text_from_image(photo.stream)
        except OCRUnavailableError as exc:
            return render_template("scanner_ocr.html", error=str(exc))
        if not extracted_text.strip():
            return render_template(
                "scanner_ocr.html",
                error="Couldn't find any readable text in that photo. Try getting closer, "
                "reducing glare, and keeping the label as flat/straight-on as possible.",
            )
        session["ocr_ingredients"] = extracted_text
        return redirect(url_for("products.new_product"))
    return render_template("scanner_ocr.html", error=None)
