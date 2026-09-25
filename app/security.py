"""Web-app hardening shared by every route: CSRF, login throttling, headers.

The app has a single user and no forms library, so rather than threading a
CSRF token through every template, state-changing requests are checked for a
same-origin Origin (or Referer) header, and the session cookie is marked
SameSite=Lax so browsers don't attach it to cross-site POSTs in the first
place. Together those stop another site from submitting forms on the logged-in
user's behalf.
"""

import time
from urllib.parse import urlparse

from flask import abort, request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# CDNs the templates load scripts and fonts from. Every <script> from them is
# also pinned with a Subresource Integrity hash in the template.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://unpkg.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    # Product photos come from Open Beauty Facts; html5-qrcode draws frames
    # through data:/blob: URLs.
    "img-src 'self' data: blob: https:",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def _origin_host(value):
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return parsed.netloc.lower()


def check_same_origin():
    """before_request hook: reject cross-site form submissions (CSRF)."""
    if request.method in SAFE_METHODS:
        return None

    origin = request.headers.get("Origin")
    if origin is None:
        referer = request.headers.get("Referer")
        if referer is None:
            # Browsers always send one of the two on a form POST, so a request
            # with neither isn't coming from a page in someone's browser - and
            # without the session cookie such a client can't act as the user.
            return None
        origin = referer

    if _origin_host(origin) != request.host.lower():
        abort(403, description="Cross-site request blocked.")
    return None


def set_security_headers(response):
    """after_request hook: standard browser hardening headers."""
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Pages show personal data; keep them out of shared/proxy caches.
    if request.endpoint != "static":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def safe_redirect_target(target):
    """Return target if it's a path on this site, else None (no open redirects)."""
    if not target:
        return None
    target = target.strip()
    # "//evil.com" and "/\evil.com" are treated by browsers as other hosts.
    if not target.startswith("/") or target.startswith("//") or target.startswith("/\\"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


def is_safe_external_url(url):
    """Only plain http(s) links may be stored/rendered as hrefs (no javascript:)."""
    if not url:
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class LoginThrottle:
    """Global failed-login counter guarding the single account.

    Global rather than per-IP: behind Railway's proxy the client address comes
    from a header an attacker controls. One account uses this app, so a
    lockout costs its owner one short wait and costs an attacker the attack.
    In-process state, which matches the single gunicorn worker in Procfile.
    """

    def __init__(self, max_failures=5, window_seconds=900, lockout_seconds=900):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._failures = []

    def remaining(self):
        now = time.time()
        self._failures = [t for t in self._failures if now - t < self.window_seconds]
        if len(self._failures) < self.max_failures:
            return 0
        return max(int(self.lockout_seconds - (now - self._failures[-1])), 0)

    def record_failure(self):
        self._failures.append(time.time())

    def reset(self):
        self._failures.clear()
