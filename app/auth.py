import hmac

import click
from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.security import LoginThrottle, safe_redirect_target

auth_bp = Blueprint("auth", __name__)

login_throttle = LoginThrottle()

# Endpoints reachable without being logged in.
PUBLIC_ENDPOINTS = {"auth.login", "static"}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        locked_for = login_throttle.remaining()
        if locked_for:
            # Don't even check the password while locked out, so the throttle
            # can't be worn down by continued guessing.
            minutes = locked_for // 60 + 1
            error = f"Too many failed attempts. Try again in {minutes} minute(s)."
            return render_template("login.html", error=error), 429

        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_username = current_app.config.get("AUTH_USERNAME")
        expected_hash = current_app.config.get("AUTH_PASSWORD_HASH")

        credentials_configured = bool(expected_username and expected_hash)
        if not credentials_configured:
            error = "Login isn't set up yet — run `flask set-password`."
            return render_template("login.html", error=error)

        # Always run the hash check and compare in constant time, so response
        # timing doesn't reveal whether the username was right.
        password_ok = check_password_hash(expected_hash, password)
        username_ok = hmac.compare_digest(username.encode(), expected_username.encode())
        if username_ok and password_ok:
            login_throttle.reset()
            session.clear()
            session["logged_in"] = True
            session.permanent = True
            next_url = safe_redirect_target(request.args.get("next"))
            return redirect(next_url or url_for("profile.home"))

        login_throttle.record_failure()
        return render_template("login.html", error="Incorrect username or password."), 401
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
