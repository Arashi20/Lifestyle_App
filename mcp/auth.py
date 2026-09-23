"""Bearer token authentication shared by the REST and MCP surfaces.

The main app has no users table: its login gate checks AUTH_USERNAME and
AUTH_PASSWORD_HASH from the environment. This service reads the same two
variables, so a valid token simply means "the app's one user".
"""

import hmac
from functools import wraps

from flask import jsonify, request

import config


def bearer_token():
    """Pull the token out of the Authorization header, or out of X-API-Key."""
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return request.headers.get('X-API-Key', '').strip()


def check_static_token(token):
    """Compare against the configured static tokens in constant time."""
    return any(hmac.compare_digest(token, valid) for valid in config.api_tokens())


def resolve_token(token):
    """Return the username a token belongs to, or None."""
    if not token:
        return None

    if check_static_token(token):
        return config.auth_username() or 'api-token'

    if config.oauth_enabled() and config.credentials_configured():
        from oauth import verify_access_token

        claims = verify_access_token(token)
        if claims is not None:
            return claims['user']

    return None


def challenge(message, status=401):
    """401 pointing the client at our OAuth metadata (RFC 9728)."""
    response = jsonify({'error': 'unauthorized', 'message': message})
    response.status_code = status
    metadata = f'{config.public_base_url(request)}/.well-known/oauth-protected-resource'
    response.headers['WWW-Authenticate'] = (
        f'Bearer realm="lifestyle", resource_metadata="{metadata}"'
    )
    return response


def authenticate():
    """Return ``(username, None)`` on success or ``(None, response)`` on failure."""
    oauth_usable = config.oauth_enabled() and config.credentials_configured()
    if not config.api_tokens() and not oauth_usable:
        response = jsonify({
            'error': 'not_configured',
            'message': ('Set AUTH_USERNAME and AUTH_PASSWORD_HASH (the same values '
                        'as the main app) for OAuth, or API_READ_TOKEN, to use '
                        'this connector.'),
        })
        response.status_code = 503
        return None, response

    token = bearer_token()
    if not token:
        return None, challenge('Missing bearer token')

    username = resolve_token(token)
    if username is None:
        return None, challenge('Invalid or expired token')
    return username, None


def token_required(view):
    """Wrap a view so it only runs for an authenticated caller."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        _, error = authenticate()
        if error is not None:
            return error
        return view(*args, **kwargs)

    return wrapper
