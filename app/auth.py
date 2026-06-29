"""Microsoft Entra ID (Azure AD) SSO — a single whole-app auth gate.

When the Azure settings are configured, every request must carry either a valid
login session (humans, via the OIDC code flow) or the `secret-sauce` API key
(machine callers). Unauthenticated browser navigations are redirected to Microsoft
login; other requests get 401. With no Azure settings AND no api_key, the gate is
a no-op so local dev runs unauthenticated.
"""
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings

# Paths reachable without auth: the login flow itself, static assets, health probe.
_PUBLIC_PREFIXES = ("/auth/", "/assets/")
_PUBLIC_PATHS = {"/health"}

oauth = OAuth()


def _sso_enabled(s) -> bool:
    return bool(s.azure_tenant_id and s.azure_client_id and s.azure_client_secret and s.session_secret)


def _safe_next(path: str) -> str:
    """A local redirect target, guarding against open/protocol-relative redirects."""
    return path if path.startswith("/") and not path.startswith("//") else "/"


def register_auth(app) -> None:
    """Wire SSO routes + the auth gate onto the app (no-op in local dev)."""
    s = get_settings()
    sso = _sso_enabled(s)
    if not sso and not s.api_key:
        return  # nothing to enforce — open for local dev

    if sso:
        oauth.register(
            name="azure",
            client_id=s.azure_client_id,
            client_secret=s.azure_client_secret,
            server_metadata_url=(
                f"https://login.microsoftonline.com/{s.azure_tenant_id}"
                "/v2.0/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid profile email"},
        )

        @app.get("/auth/login")
        async def login(request: Request):
            request.session["next"] = _safe_next(request.query_params.get("next", "/"))
            return await oauth.azure.authorize_redirect(request, request.url_for("auth_callback"))

        @app.get("/auth/callback", name="auth_callback")
        async def callback(request: Request):
            token = await oauth.azure.authorize_access_token(request)
            claims = token.get("userinfo") or {}
            request.session["user"] = {
                "name": claims.get("name"),
                "email": claims.get("email") or claims.get("preferred_username"),
            }
            return RedirectResponse(request.session.pop("next", "/"))

        @app.get("/auth/logout")
        async def logout(request: Request):
            request.session.clear()
            return RedirectResponse("/")

        @app.get("/auth/me")
        async def me(request: Request):
            return request.session.get("user")

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)
        if s.api_key and request.headers.get("secret-sauce") == s.api_key:
            return await call_next(request)  # machine caller
        if sso and request.session.get("user"):
            return await call_next(request)  # signed-in human
        if sso and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/auth/login?next={_safe_next(path)}")
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    # SessionMiddleware must wrap the gate so `request.session` exists when the gate
    # reads it — add_middleware makes the last-added middleware the outermost.
    if sso:
        app.add_middleware(
            SessionMiddleware,
            secret_key=s.session_secret,
            https_only=True,
            same_site="lax",
        )
