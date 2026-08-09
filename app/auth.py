import click
from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth", __name__)

# Endpoints reachable without being logged in.
PUBLIC_ENDPOINTS = {"auth.login", "static"}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_username = current_app.config.get("AUTH_USERNAME")
        expected_hash = current_app.config.get("AUTH_PASSWORD_HASH")

        credentials_configured = bool(expected_username and expected_hash)
        valid = (
            credentials_configured
            and username == expected_username
            and check_password_hash(expected_hash, password)
        )
        if valid:
            session.clear()
            session["logged_in"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("profile.home"))

        error = (
            "Login isn't set up yet — run `flask set-password`."
            if not credentials_configured
            else "Incorrect username or password."
        )
        return render_template("login.html", error=error)
    return render_template("login.html", error=None)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def require_login():
    """Registered as a before_request hook — gates every page but login/static."""
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get("logged_in"):
        return redirect(url_for("auth.login", next=request.path))


def register_cli(app):
    @app.cli.command("set-password")
    def set_password():
        """Interactively set the login username/password (writes to .env)."""
        import getpass

        from dotenv import set_key

        username = input("Username: ").strip()
        if not username:
            click.echo("No username entered, nothing saved.")
            return
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if not password:
            click.echo("No password entered, nothing saved.")
            return
        if password != confirm:
            click.echo("Passwords didn't match, nothing saved.")
            return

        set_key(".env", "AUTH_USERNAME", username)
        set_key(".env", "AUTH_PASSWORD_HASH", generate_password_hash(password))
        click.echo("Saved to .env. Restart the dev server for it to take effect.")
