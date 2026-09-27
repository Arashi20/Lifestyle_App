from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, flash, url_for

from app import db
from app.models import Haircut
from app.security import is_safe_external_url

haircuts_bp = Blueprint("haircuts", __name__, url_prefix="/haircuts")


def _parse_date(value):
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _photo_url(value):
    """Keep only http(s) links: the URL is rendered as an href, so a
    javascript: URL would run script when clicked."""
    value = (value or "").strip()
    if not value:
        return None
    if not is_safe_external_url(value):
        flash("Photo link ignored — it must start with http:// or https://.", "error")
        return None
    return value


@haircuts_bp.route("/")
def list_haircuts():
    haircuts = Haircut.query.order_by(Haircut.date.desc()).all()
    return render_template("haircuts/list.html", haircuts=haircuts)


@haircuts_bp.route("/new", methods=["GET", "POST"])
def new_haircut():
    if request.method == "POST":
        haircut = Haircut(
            salon_or_barber=request.form.get("salon_or_barber"),
            date=_parse_date(request.form.get("date")),
            description=request.form.get("description"),
            how_to_request=request.form.get("how_to_request"),
            rating=request.form.get("rating") or None,
            photo_url=_photo_url(request.form.get("photo_url")),
        )
        db.session.add(haircut)
        db.session.commit()
        flash("Haircut added.", "success")
        return redirect(url_for("haircuts.list_haircuts"))
    return render_template("haircuts/form.html", haircut=None)


@haircuts_bp.route("/<int:haircut_id>")
def view_haircut(haircut_id):
    haircut = Haircut.query.get_or_404(haircut_id)
    return render_template("haircuts/detail.html", haircut=haircut)


@haircuts_bp.route("/<int:haircut_id>/edit", methods=["GET", "POST"])
def edit_haircut(haircut_id):
    haircut = Haircut.query.get_or_404(haircut_id)
    if request.method == "POST":
        haircut.salon_or_barber = request.form.get("salon_or_barber")
        haircut.date = _parse_date(request.form.get("date"))
        haircut.description = request.form.get("description")
        haircut.how_to_request = request.form.get("how_to_request")
        haircut.rating = request.form.get("rating") or None
        haircut.photo_url = _photo_url(request.form.get("photo_url"))
        db.session.commit()
        flash("Changes saved.", "success")
        return redirect(url_for("haircuts.view_haircut", haircut_id=haircut.id))
    return render_template("haircuts/form.html", haircut=haircut)


@haircuts_bp.route("/<int:haircut_id>/delete", methods=["POST"])
def delete_haircut(haircut_id):
    haircut = Haircut.query.get_or_404(haircut_id)
    db.session.delete(haircut)
    db.session.commit()
    flash("Haircut deleted.", "success")
    return redirect(url_for("haircuts.list_haircuts"))
