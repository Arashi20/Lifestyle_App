from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from config import Config

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so Flask-Migrate can detect them
    from app import models  # noqa: F401

    # Register blueprints
    from app.auth import auth_bp, require_login
    from app.routes.profile import profile_bp
    from app.routes.products import products_bp
    from app.routes.haircuts import haircuts_bp
    from app.routes.scanner import scanner_bp
    from app.routes.watchlist import watchlist_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(haircuts_bp)
    app.register_blueprint(scanner_bp)
    app.register_blueprint(watchlist_bp)

    app.before_request(require_login)

    from app.seed import register_cli as register_watchlist_cli
    from app.auth import register_cli as register_auth_cli
    register_watchlist_cli(app)
    register_auth_cli(app)

    return app
