"""Standalone read-only connector for the Skincare & Haircare Tracker.

Deployed as its own Railway service pointing at this folder, sharing the main
app's Postgres database and login variables. It exposes the profile, products,
haircuts and ingredient watchlist over MCP (for Claude custom connectors) and
over plain REST, and it never writes:

  * no route accepts anything but GET or the MCP/OAuth POSTs;
  * no collector issues anything but SELECT;
  * every database connection is opened read-only, so even a bug in this
    service could not change the data - the database itself would refuse;
  * the schema is owned entirely by the main app's migrations.
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

# Before `config` is read, so a local .env is honored by every entry point.
load_dotenv()

from flask import Flask, jsonify, request  # noqa: E402
from sqlalchemy import event  # noqa: E402

import config  # noqa: E402
from auth import authenticate  # noqa: E402
from mcp_endpoint import TOOLS, mcp_bp  # noqa: E402
from models import db  # noqa: E402
from oauth import oauth_bp  # noqa: E402
from rest_api import rest_api  # noqa: E402


def make_connections_read_only(engine):
    """Open every pooled connection in read-only mode.

    Postgres: each transaction on the connection defaults to READ ONLY, so an
    INSERT/UPDATE/DELETE fails with "cannot execute ... in a read-only
    transaction". SET is transactional in Postgres, hence the commit - a later
    rollback would otherwise undo it. SQLite (local dev): query_only.
    """
    dialect = engine.dialect.name

    @event.listens_for(engine, 'connect')
    def _set_read_only(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        if dialect == 'postgresql':
            cursor.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
            cursor.close()
            dbapi_connection.commit()
        elif dialect == 'sqlite':
            cursor.execute('PRAGMA query_only = ON')
            cursor.close()


def connection_is_read_only():
    if db.engine.dialect.name == 'postgresql':
        return db.session.execute(db.text('SHOW transaction_read_only')).scalar() == 'on'
    if db.engine.dialect.name == 'sqlite':
        return db.session.execute(db.text('PRAGMA query_only')).scalar() == 1
    return None


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.secret_key()
    app.config['SQLALCHEMY_DATABASE_URI'] = config.database_url()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 2,          # a connector serves one user; keep it small
            'pool_recycle': 300,
            'pool_pre_ping': True,
            'max_overflow': 2,
            'pool_timeout': 10,
        }

    # This service reads a schema the main app owns: no create_all, no migration.
    db.init_app(app)
    with app.app_context():
        make_connections_read_only(db.engine)

    app.register_blueprint(rest_api)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(oauth_bp)

    @app.before_request
    def enforce_allowed_hosts():
        """Reject requests carrying an unexpected Host header.

        An MCP server on a public URL should only answer to its own hostname,
        so a page that resolves someone else's name to this address cannot
        talk to it.
        """
        allowed = config.allowed_hosts()
        if not allowed:
            return None
        host = (request.host or '').split(':')[0]
        if host in allowed or host in ('localhost', '127.0.0.1'):
            return None
        return jsonify({'error': 'forbidden', 'message': 'Unexpected Host header'}), 403

    @app.route('/', methods=['GET'])
    def index():
        """What this service is, without giving anything away to an anonymous caller."""
        base = config.public_base_url(request)
        return jsonify({
            'service': 'lifestyle-connector',
            'access': 'read-only',
            'areas': ['profile', 'products', 'haircuts', 'ingredient watchlist'],
            'mcp_endpoint': f'{base}/mcp',
            'tools': [tool['name'] for tool in TOOLS],
            'rest_endpoints': [f'{base}/api/v1/{name}' for name in
                               ('overview', 'products', 'haircuts', 'watchlist',
                                'check-ingredients', 'ping')],
            'authorization_server': base,
        })

    @app.route('/healthz', methods=['GET'])
    def healthz():
        """Liveness probe, and the first place to look when Claude cannot connect.

        Reports the settings that decide whether the OAuth handshake can work -
        the base URL Claude is handed and the host this request arrived on -
        without exposing any secret.
        """
        base = config.public_base_url(request)
        report = {
            'status': 'ok',
            'public_base_url': base,
            'request_host': request.host,
            'public_url_matches_request': urlparse(base).hostname == request.host.split(':')[0],
            'allowed_hosts': config.allowed_hosts() or 'any',
            'login_configured': config.credentials_configured(),
            'oauth_enabled': config.oauth_enabled(),
            'dynamic_registration': config.dynamic_registration_enabled(),
        }
        warning = config.public_url_warning()
        if not config.credentials_configured():
            warning = ((warning + ' ') if warning else '') + (
                'AUTH_USERNAME / AUTH_PASSWORD_HASH are not set, so nobody can '
                'sign in to approve Claude. Reference the main service\'s values.')
        if warning:
            report['warning'] = warning

        try:
            report['read_only_connection'] = connection_is_read_only()
            report['database'] = 'reachable'
        except Exception:
            app.logger.exception('Health check could not reach the database')
            report['status'] = 'degraded'
            report['database'] = 'unreachable'
            return jsonify(report), 503

        return jsonify(report)

    @app.route('/whoami', methods=['GET'])
    def whoami():
        """Which account a token maps to - handy while setting the connector up."""
        username, error = authenticate()
        if error is not None:
            return error
        return jsonify({'user': username, 'scope': 'read'})

    warning = config.public_url_warning()
    if warning:
        app.logger.warning('Connector misconfiguration: %s', warning)

    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)),
            debug=config.flag('FLASK_DEBUG', '0'))
