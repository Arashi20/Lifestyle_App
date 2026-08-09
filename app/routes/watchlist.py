from flask import Blueprint, render_template, request, redirect, flash, url_for

from app import db
from app.models import WatchlistItem

watchlist_bp = Blueprint("watchlist", __name__, url_prefix="/watchlist")

SEVERITY_ORDER = {"avoid": 0, "caution": 1, "good": 2}


@watchlist_bp.route("/")
def list_watchlist():
    severity_filter = request.args.get("severity")
    query = WatchlistItem.query
    if severity_filter:
        query = query.filter_by(severity=severity_filter)
    items = query.all()
    items.sort(key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.ingredient_name.lower()))
    return render_template("watchlist/list.html", items=items, severity_filter=severity_filter)


@watchlist_bp.route("/new", methods=["GET", "POST"])
def new_watchlist_item():
    if request.method == "POST":
        item = WatchlistItem(
            ingredient_name=request.form["ingredient_name"],
            reason=request.form.get("reason"),
            severity=request.form.get("severity", "caution"),
        )
        db.session.add(item)
        db.session.commit()
        flash(f'"{item.ingredient_name}" added to your watchlist.', "success")
        return redirect(url_for("watchlist.list_watchlist"))
    return render_template("watchlist/form.html", item=None)


@watchlist_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit_watchlist_item(item_id):
    item = WatchlistItem.query.get_or_404(item_id)
    if request.method == "POST":
        item.ingredient_name = request.form["ingredient_name"]
        item.reason = request.form.get("reason")
        item.severity = request.form.get("severity", item.severity)
        db.session.commit()
        flash("Changes saved.", "success")
        return redirect(url_for("watchlist.list_watchlist"))
    return render_template("watchlist/form.html", item=item)


@watchlist_bp.route("/<int:item_id>/delete", methods=["POST"])
def delete_watchlist_item(item_id):
    item = WatchlistItem.query.get_or_404(item_id)
    name = item.ingredient_name
    db.session.delete(item)
    db.session.commit()
    flash(f'"{name}" removed from your watchlist.', "success")
    return redirect(url_for("watchlist.list_watchlist"))
