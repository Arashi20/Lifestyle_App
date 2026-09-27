"""OAuth 2.1 authorization server for the Claude custom connector.

Claude's custom connectors authenticate with OAuth, so this implements the
slice of OAuth 2.1 a remote MCP server needs:

  * RFC 8414 authorization-server metadata and RFC 9728 protected-resource
    metadata, so Claude discovers the endpoints on its own;
  * RFC 7591 dynamic client registration (Claude registers itself), plus an
    optional pre-shared client from MCP_OAUTH_CLIENT_ID / _CLIENT_SECRET;
  * authorization code with PKCE (S256), and refresh tokens.

The user signs in with their normal app username and password, checked
against the same AUTH_USERNAME / AUTH_PASSWORD_HASH variables the main app's
login gate reads. Codes, tokens and client secrets are HMAC-signed values
derived from the signing key rather than database rows, so this service needs
no tables of its own - it never writes to the database at all. Rotating the
key revokes everything it has issued, and so does changing the app login:
every token carries a fingerprint of the credentials it was issued under.
"""

import hashlib
import hmac
import os
import secrets
import time
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, urlparse

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template_string,
    request,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

import config

oauth_bp = Blueprint('oauth', __name__)

# Where Claude sends the browser back after approval. Kept as the default
# allow-list so a pre-shared client works without extra configuration.
DEFAULT_REDIRECT_URIS = [
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
]

# Callback hosts that belong to Claude. A client registering any other one is
# not necessarily hostile, but the approval page says so plainly.
KNOWN_CLIENT_HOSTS = {'claude.ai', 'claude.com'}

AUTH_CODE_TTL = 300                    # seconds; codes are single use
ACCESS_TOKEN_TTL = 3600                # 1 hour
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
READ_SCOPE = 'read'

# Codes already exchanged, so a replay inside the TTL fails. In-process only,
# which covers a single-worker deployment; a code surviving a restart is still
# bounded by AUTH_CODE_TTL.
_used_codes = set()

# The approval page is a public form guarding real account credentials, so
# failed attempts are throttled. The count is global rather than per-IP: this
# service sits behind a proxy, so the client address it sees comes from a
# caller-supplied header that an attacker could vary at will. One account uses
# this connector, so a global lockout costs that user one wait and costs an
# attacker the whole attack.
MAX_FAILED_LOGINS = 5
FAILURE_WINDOW_SECONDS = 900   # 15 minutes
LOCKOUT_SECONDS = 900
_failed_logins = []


def _prune_failures(now):
    global _failed_logins
    _failed_logins = [t for t in _failed_logins if now - t < FAILURE_WINDOW_SECONDS]


def lockout_remaining():
    """Seconds until sign-in is allowed again, or 0 when it is allowed now."""
    now = time.time()
    _prune_failures(now)
    if len(_failed_logins) < MAX_FAILED_LOGINS:
        return 0
    remaining = int(LOCKOUT_SECONDS - (now - _failed_logins[-1]))
    return max(remaining, 0)


def record_login_failure():
    _failed_logins.append(time.time())


def clear_login_failures():
    _failed_logins.clear()


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

def static_client():
    """The optional pre-shared client configured through the environment."""
    client_id = os.getenv('MCP_OAUTH_CLIENT_ID')
    if not client_id:
        return None
    return {
        'client_id': client_id,
        'client_secret': os.getenv('MCP_OAUTH_CLIENT_SECRET'),
        'redirect_uris': config.csv_env('MCP_OAUTH_REDIRECT_URIS') or list(DEFAULT_REDIRECT_URIS),
        'client_name': os.getenv('MCP_OAUTH_CLIENT_NAME', 'Pre-configured client'),
    }


def derive_client_secret(client_id):
    key = current_app.config['SECRET_KEY'].encode()
    digest = hmac.new(key, client_id.encode(), hashlib.sha256).digest()
    return urlsafe_b64encode(digest).rstrip(b'=').decode()


def register_client(redirect_uris, client_name):
    """Mint a self-describing client_id; its secret is derived from it."""
    payload = {'redirect_uris': redirect_uris, 'name': client_name, 'iat': int(time.time())}
    client_id = _serializer('mcp-oauth-client').dumps(payload)
    return {
        'client_id': client_id,
        'client_secret': derive_client_secret(client_id),
        'redirect_uris': redirect_uris,
        'client_name': client_name,
    }


def load_client(client_id):
    """Resolve a client_id to its registration, or None if it isn't ours."""
    static = static_client()
    if static and hmac.compare_digest(client_id, static['client_id']):
        return static
    try:
        payload = _serializer('mcp-oauth-client').loads(client_id)
    except BadSignature:
        return None
    return {
        'client_id': client_id,
        'client_secret': derive_client_secret(client_id),
        'redirect_uris': payload.get('redirect_uris') or [],
        'client_name': payload.get('name') or 'Unnamed client',
    }


def client_secret_matches(client, presented):
    expected = client.get('client_secret')
    if not expected:
        # A public client registered without a secret: PKCE is the protection.
        return True
    return bool(presented) and hmac.compare_digest(expected, presented)


def redirect_uri_allowed(client, redirect_uri):
    return redirect_uri in (client.get('redirect_uris') or [])


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def _claims(client_id, token_type):
    return {
        'user': config.auth_username(),
        'fp': config.credentials_fingerprint(),
        'client_id': client_id,
        'scope': READ_SCOPE,
        'type': token_type,
    }


def login_still_current(payload):
    """A grant is only good while the app login it was issued under is unchanged."""
    return (config.credentials_configured()
            and hmac.compare_digest(str(payload.get('user', '')), config.auth_username())
            and hmac.compare_digest(str(payload.get('fp', '')), config.credentials_fingerprint()))


def issue_access_token(client_id):
    return _serializer('mcp-oauth-access').dumps(_claims(client_id, 'access'))


def issue_refresh_token(client_id):
    return _serializer('mcp-oauth-refresh').dumps(_claims(client_id, 'refresh'))


def verify_access_token(token):
    """Return the token's claims, or None if invalid, expired or revoked."""
    try:
        payload = _serializer('mcp-oauth-access').loads(token, max_age=ACCESS_TOKEN_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if payload.get('type') != 'access' or payload.get('scope') != READ_SCOPE:
        return None
    return payload if login_still_current(payload) else None


def verify_refresh_token(token):
    try:
        payload = _serializer('mcp-oauth-refresh').loads(token, max_age=REFRESH_TOKEN_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if payload.get('type') != 'refresh' or not login_still_current(payload):
        return None
    return payload


def issue_authorization_code(client_id, redirect_uri, code_challenge):
    return _serializer('mcp-oauth-code').dumps({
        'user': config.auth_username(),
        'fp': config.credentials_fingerprint(),
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'code_challenge': code_challenge,
        'nonce': secrets.token_urlsafe(8),
    })


def consume_authorization_code(code):
    try:
        payload = _serializer('mcp-oauth-code').loads(code, max_age=AUTH_CODE_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if code in _used_codes:
        return None
    _used_codes.add(code)
    if len(_used_codes) > 1000:
        _used_codes.clear()
    return payload


def pkce_matches(code_challenge, code_verifier):
    if not code_challenge:
        return False
    try:
        verifier = code_verifier.encode('ascii')
    except UnicodeEncodeError:
        return False
    digest = hashlib.sha256(verifier).digest()
    expected = urlsafe_b64encode(digest).rstrip(b'=').decode()
    return hmac.compare_digest(expected, code_challenge)


# --------------------------------------------------------------------------
# Discovery metadata
# --------------------------------------------------------------------------

def _protected_resource_metadata():
    base = config.public_base_url(request)
    return jsonify({
        'resource': f'{base}/mcp',
        'authorization_servers': [base],
        'scopes_supported': [READ_SCOPE],
        'bearer_methods_supported': ['header'],
        'resource_documentation': f'{base}/',
    })


def _authorization_server_metadata():
    base = config.public_base_url(request)
    metadata = {
        'issuer': base,
        'authorization_endpoint': f'{base}/oauth/authorize',
        'token_endpoint': f'{base}/oauth/token',
        'scopes_supported': [READ_SCOPE],
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': [
            'client_secret_post', 'client_secret_basic', 'none',
        ],
    }
    if config.dynamic_registration_enabled():
        metadata['registration_endpoint'] = f'{base}/oauth/register'
    return jsonify(metadata)


# Clients probe both the bare path and the path with the resource appended.
oauth_bp.add_url_rule('/.well-known/oauth-protected-resource',
                      'protected_resource_metadata', _protected_resource_metadata)
oauth_bp.add_url_rule('/.well-known/oauth-protected-resource/mcp',
                      'protected_resource_metadata_mcp', _protected_resource_metadata)
oauth_bp.add_url_rule('/.well-known/oauth-authorization-server',
                      'authorization_server_metadata', _authorization_server_metadata)
oauth_bp.add_url_rule('/.well-known/oauth-authorization-server/mcp',
                      'authorization_server_metadata_mcp', _authorization_server_metadata)


# --------------------------------------------------------------------------
# Dynamic client registration
# --------------------------------------------------------------------------

@oauth_bp.route('/oauth/register', methods=['POST'])
def register():
    if not config.oauth_enabled() or not config.dynamic_registration_enabled():
        return jsonify({'error': 'access_denied',
                        'error_description': 'Dynamic client registration is disabled'}), 403

    body = request.get_json(silent=True) or {}
    redirect_uris = body.get('redirect_uris') or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return jsonify({'error': 'invalid_redirect_uri',
                        'error_description': 'redirect_uris is required'}), 400
    if len(redirect_uris) > 10:
        return jsonify({'error': 'invalid_redirect_uri',
                        'error_description': 'Too many redirect_uris'}), 400
    for uri in redirect_uris:
        if not isinstance(uri, str):
            return jsonify({'error': 'invalid_redirect_uri',
                            'error_description': 'redirect_uris must be strings'}), 400
        parsed = urlparse(uri)
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1'):
            return jsonify({'error': 'invalid_redirect_uri',
                            'error_description': f'redirect_uri must use https: {uri}'}), 400

    client_name = body.get('client_name')
    if not isinstance(client_name, str) or not client_name.strip():
        client_name = 'MCP client'
    client = register_client(redirect_uris, client_name[:100])
    return jsonify({
        'client_id': client['client_id'],
        'client_secret': client['client_secret'],
        'client_id_issued_at': int(time.time()),
        'client_secret_expires_at': 0,   # never expires
        'redirect_uris': redirect_uris,
        'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'],
        'token_endpoint_auth_method': 'client_secret_post',
        'scope': READ_SCOPE,
    }), 201


# --------------------------------------------------------------------------
# Authorization endpoint
# --------------------------------------------------------------------------

APPROVAL_PAGE = """
<!doctype html>
<title>Connect to Skincare &amp; Haircare Tracker</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background:#111; color:#eee;
         display:flex; min-height:100vh; margin:0; align-items:center; justify-content:center; }
  .card { background:#1c1c1e; padding:28px; border-radius:14px; width:min(360px, 90vw); }
  h1 { font-size:19px; margin:0 0 6px; }
  p, ul { color:#9b9b9f; font-size:14px; line-height:1.5; }
  ul { padding-left:20px; }
  label { font-size:13px; color:#c7c7cc; }
  input { width:100%; box-sizing:border-box; padding:11px; margin:6px 0 14px;
          border-radius:8px; border:1px solid #3a3a3c; background:#2c2c2e; color:#fff; }
  button { width:100%; padding:12px; border:0; border-radius:8px; background:#0a84ff;
           color:#fff; font-size:15px; font-weight:600; }
  .err { color:#ff6b6b; }
  .dest { color:#c7c7cc; }
  .warn { background:#3a2a10; border:1px solid #7a5c1e; color:#ffd479;
          padding:10px 12px; border-radius:8px; }
  button[disabled] { background:#3a3a3c; color:#8e8e93; }
</style>
<div class="card">
  <h1>Grant read-only access</h1>
  <p><strong>{{ client_name }}</strong> is asking to read:</p>
  <ul><li>Profile &amp; sleep schedule</li><li>Products &amp; ingredient scores</li>
      <li>Haircuts</li><li>Ingredient watchlist</li></ul>
  <p>It cannot add, change or delete anything.</p>
  <p class="dest">After you approve, the access is sent to <strong>{{ redirect_host }}</strong>.</p>
  {% if unrecognized %}
  <p class="warn">This is not one of Claude&rsquo;s usual addresses. If you did not
  start this from Claude&rsquo;s connector settings yourself, close this page:
  approving it would hand your data to whoever sent you here.</p>
  {% endif %}
  {% if not configured %}
  <p class="err">Sign-in is not set up on this connector: set AUTH_USERNAME and
  AUTH_PASSWORD_HASH to the same values as the main app.</p>
  {% endif %}
  {% if error %}<p class="err">{{ error }}</p>{% endif %}
  {% if locked_for %}
  <p class="err">Too many failed sign-in attempts. Try again in
  {{ (locked_for // 60) + 1 }} minute(s).</p>
  {% endif %}
  <form method="post">
    {% for key, value in params.items() %}
    <input type="hidden" name="{{ key }}" value="{{ value }}">
    {% endfor %}
    <label>Username</label>
    <input name="username" autocomplete="username" autofocus>
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password"
           {% if locked_for %}disabled{% endif %}>
    <button type="submit" {% if locked_for %}disabled{% endif %}>
      Approve read-only access</button>
  </form>
</div>
"""


def _describe_client(client, redirect_uri):
    """Identity to show on the approval page.

    The name comes from whoever registered the client, so it is untrusted text -
    Jinja escapes it, and it is shown next to the address the access would
    actually be sent to, which is the part an attacker cannot fake.
    """
    name = (client.get('client_name') or 'Unnamed client').strip()[:60] or 'Unnamed client'
    host = urlparse(redirect_uri).hostname or redirect_uri
    return {
        'client_name': name,
        'redirect_host': host,
        'unrecognized': host not in KNOWN_CLIENT_HOSTS,
    }


def _render_approval(client, redirect_uri, params, error=None, status=200):
    locked_for = lockout_remaining()
    page = render_template_string(
        APPROVAL_PAGE, params=params, error=error, locked_for=locked_for,
        configured=config.credentials_configured(),
        **_describe_client(client, redirect_uri))
    response = make_response(page)
    response.status_code = 429 if locked_for else status
    if locked_for:
        response.headers['Retry-After'] = str(locked_for)
    return response


def credentials_match(username, password):
    """The main app's login check, against the same environment variables."""
    # Always run the hash check, so a wrong username costs the same time as a
    # wrong password and does not reveal which one was right.
    password_ok = check_password_hash(config.auth_password_hash(), password)
    username_ok = hmac.compare_digest(username.encode(), config.auth_username().encode())
    return username_ok and password_ok


def _authorize_error(redirect_uri, state, error, description):
    """Report back to the client once the redirect_uri is validated."""
    params = {'error': error, 'error_description': description}
    if state:
        params['state'] = state
    return redirect(f'{redirect_uri}?{urlencode(params)}')


@oauth_bp.route('/oauth/authorize', methods=['GET', 'POST'])
def authorize():
    if not config.oauth_enabled():
        return jsonify({'error': 'access_denied',
                        'error_description': 'This connector is disabled'}), 403

    source = request.form if request.method == 'POST' else request.args
    client_id = source.get('client_id', '')
    redirect_uri = source.get('redirect_uri', '')
    state = source.get('state', '')
    code_challenge = source.get('code_challenge', '')
    code_challenge_method = source.get('code_challenge_method', '')
    response_type = source.get('response_type', 'code')

    client = load_client(client_id) if client_id else None
    if client is None:
        return jsonify({'error': 'invalid_client',
                        'error_description': 'Unknown client_id'}), 400
    if not redirect_uri_allowed(client, redirect_uri):
        return jsonify({'error': 'invalid_request',
                        'error_description': 'redirect_uri is not registered for this client'}), 400

    if response_type != 'code':
        return _authorize_error(redirect_uri, state, 'unsupported_response_type',
                                'Only the authorization code flow is supported')
    if code_challenge_method != 'S256' or not code_challenge:
        return _authorize_error(redirect_uri, state, 'invalid_request',
                                'PKCE with code_challenge_method=S256 is required')

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': code_challenge_method,
        'response_type': response_type,
        'scope': source.get('scope', READ_SCOPE),
    }

    if request.method == 'GET':
        return _render_approval(client, redirect_uri, params)

    # Refuse to even check the password while locked out, so the throttle
    # cannot be worn down by continued guessing.
    if lockout_remaining():
        return _render_approval(client, redirect_uri, params)

    if not config.credentials_configured():
        return _render_approval(client, redirect_uri, params, status=503)

    if not credentials_match(source.get('username', ''), source.get('password', '')):
        record_login_failure()
        return _render_approval(client, redirect_uri, params,
                                error='Invalid username or password', status=401)

    clear_login_failures()
    result = {'code': issue_authorization_code(client_id, redirect_uri, code_challenge)}
    if state:
        result['state'] = state
    return redirect(f'{redirect_uri}?{urlencode(result)}')


# --------------------------------------------------------------------------
# Token endpoint
# --------------------------------------------------------------------------

def _client_credentials():
    """Read client credentials from the body, or from HTTP Basic auth."""
    client_id = request.form.get('client_id')
    client_secret = request.form.get('client_secret')
    if request.authorization and request.authorization.username:
        client_id = client_id or request.authorization.username
        client_secret = client_secret or request.authorization.password
    return client_id, client_secret


def _token_error(error, description, status=400):
    return jsonify({'error': error, 'error_description': description}), status


@oauth_bp.route('/oauth/token', methods=['POST'])
def token():
    if not config.oauth_enabled():
        return _token_error('invalid_client', 'This connector is disabled', 403)

    grant_type = request.form.get('grant_type')
    client_id, client_secret = _client_credentials()
    client = load_client(client_id) if client_id else None
    if client is None:
        return _token_error('invalid_client', 'Unknown client_id', 401)
    if not client_secret_matches(client, client_secret):
        return _token_error('invalid_client', 'Client authentication failed', 401)

    if grant_type == 'authorization_code':
        code = request.form.get('code', '')
        code_verifier = request.form.get('code_verifier', '')
        payload = consume_authorization_code(code) if code else None
        if payload is None:
            return _token_error('invalid_grant', 'Authorization code is invalid, expired or used')
        if payload['client_id'] != client_id:
            return _token_error('invalid_grant', 'Code was issued to a different client')
        if payload['redirect_uri'] != request.form.get('redirect_uri', payload['redirect_uri']):
            return _token_error('invalid_grant', 'redirect_uri does not match the request')
        if not code_verifier or not pkce_matches(payload['code_challenge'], code_verifier):
            return _token_error('invalid_grant', 'PKCE verification failed')

    elif grant_type == 'refresh_token':
        payload = verify_refresh_token(request.form.get('refresh_token', ''))
        if payload is None:
            return _token_error('invalid_grant', 'Refresh token is invalid or expired')
        if payload['client_id'] != client_id:
            return _token_error('invalid_grant', 'Refresh token was issued to a different client')

    else:
        return _token_error('unsupported_grant_type', 'Use authorization_code or refresh_token')

    if not login_still_current(payload):
        return _token_error('invalid_grant', 'The app login changed since this grant was issued')

    response = jsonify({
        'access_token': issue_access_token(client_id),
        'token_type': 'Bearer',
        'expires_in': ACCESS_TOKEN_TTL,
        'refresh_token': issue_refresh_token(client_id),
        'scope': READ_SCOPE,
    })
    response.headers['Cache-Control'] = 'no-store'
    return response
