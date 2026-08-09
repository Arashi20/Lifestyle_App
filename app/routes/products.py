from flask import Blueprint, render_template, request, redirect, flash, session, url_for

from app import db
from app.models import Product, WatchlistItem
from app.services.watchlist import find_flagged_ingredients, worst_severity, goodness_score, goodness_tier

products_bp = Blueprint("products", __name__, url_prefix="/products")


@products_bp.route("/")
def list_products():
    status_filter = request.args.get("status")
    query = Product.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    products = query.order_by(Product.updated_at.desc()).all()

    watchlist_items = WatchlistItem.query.all()
    flag_severity = {}
    scores = {}
    tiers = {}
    for product in products:
        flagged = find_flagged_ingredients(product.ingredients, watchlist_items)
        flag_severity[product.id] = worst_severity(flagged)
        scores[product.id] = goodness_score(product.ingredients, watchlist_items)
        tiers[product.id] = goodness_tier(scores[product.id])

    return render_template(
        "products/list.html",
        products=products,
        status_filter=status_filter,
        flag_severity=flag_severity,
        scores=scores,
        tiers=tiers,
    )


@products_bp.route("/new", methods=["GET", "POST"])
def new_product():
    if request.method == "POST":
        product = Product(
            name=request.form["name"],
            brand=request.form.get("brand"),
            category=request.form.get("category"),
            status=request.form.get("status", "wishlist"),
            rating=request.form.get("rating") or None,
            skin_notes=request.form.get("skin_notes"),
            ingredients=request.form.get("ingredients"),
        )
        db.session.add(product)
        db.session.commit()
        flash(f'"{product.name}" added.', "success")
        return redirect(url_for("products.list_products"))
    ocr_ingredients = session.pop("ocr_ingredients", None)
    return render_template("products/form.html", product=None, ocr_ingredients=ocr_ingredients)


@products_bp.route("/<int:product_id>")
def view_product(product_id):
    product = Product.query.get_or_404(product_id)
    flagged = find_flagged_ingredients(product.ingredients)
    concerning = [item for item in flagged if item.severity in ("avoid", "caution")]
    good_matches = [item for item in flagged if item.severity == "good"]
    score = goodness_score(product.ingredients)
    tier = goodness_tier(score)
    return render_template(
        "products/detail.html",
        product=product,
        concerning=concerning,
        good_matches=good_matches,
        score=score,
        tier=tier,
    )


@products_bp.route("/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        product.name = request.form["name"]
        product.brand = request.form.get("brand")
        product.category = request.form.get("category")
        product.status = request.form.get("status", product.status)
        product.rating = request.form.get("rating") or None
        product.skin_notes = request.form.get("skin_notes")
        product.ingredients = request.form.get("ingredients")
        db.session.commit()
        flash("Changes saved.", "success")
        return redirect(url_for("products.view_product", product_id=product.id))
    return render_template("products/form.html", product=product)


@products_bp.route("/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    name = product.name
    db.session.delete(product)
    db.session.commit()
    flash(f'"{name}" deleted.', "success")
    return redirect(url_for("products.list_products"))
