"""Keycloak (OpenID Connect) sign-in, account linking and single sign-out.

Arena is a confidential client using the authorization code flow with PKCE (S256),
`state` and `nonce`. Pending attempts are stored server-side, are single use and
are bound to the browser that started them with a short-lived cookie, so a crafted
authorization link cannot sign a victim into, or link, someone else's account.
Identities are found only by (issuer, sub), never by username or email: anyone
can register a local account with any free name, so matching those would allow
account takeover. See docs/authentication.md.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import ssl
import time
from urllib.parse import quote_plus, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .accounts import interactive_user
from .auth import current_user, has_usable_password, new_session, unusable_password
from .db import get_db
from .models import OidcLoginAttempt, ServiceNotice, User, UserIdentity, now
from .moderation import record
from .permissions import is_admin
from .site_settings import setting

log = logging.getLogger(__name__)

SCOPE = "openid profile email"
ATTEMPT_SECONDS = 600
MAX_PENDING_ATTEMPTS = 5000
CLOCK_SKEW = 60
DISCOVERY_SECONDS = 3600
BROWSER_COOKIE = "arena_oidc"
COOKIE_PATH = "/api/auth/oidc"
USERNAME_MAX = User.__table__.c.username.type.length
# Hash routes only: a letter or digit first, so `//host` and `https:` never match.
NEXT_ROUTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,150}(\?[A-Za-z0-9_=&.-]{0,80})?")
# Tests install an httpx.MockTransport here; production uses the network.
transport = None
_discovery = {}


def issuer():
    return os.getenv("ARENA_OIDC_ISSUER", "").strip().rstrip("/")


def client_id():
    return os.getenv("ARENA_OIDC_CLIENT_ID", "").strip()


def client_secret():
    return os.getenv("ARENA_OIDC_CLIENT_SECRET", "").strip()


def enabled():
    return bool(issuer() and client_id() and client_secret())


def label():
    return os.getenv("ARENA_OIDC_LABEL", "").strip() or "Sign in with Keycloak"


def group_setting(name):
    # Keycloak sends full group paths such as "/arena-admins" when configured to.
    return {part.strip().lstrip("/") for part in os.getenv(name, "").split(",")} - {""}


def require_enabled():
    if not enabled():
        raise HTTPException(404, "Not Found")


router = APIRouter(
    prefix="/api", tags=["Authentication"], dependencies=[Depends(require_enabled)]
)


class LoginError(Exception):
    """A failed sign-in: `code` is shown to the browser, the message is only logged."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def public_url(request):
    configured = os.getenv("ARENA_PUBLIC_URL", "").strip()
    return (configured or str(request.base_url)).rstrip("/")


def redirect_uri(request):
    return public_url(request) + "/api/auth/oidc/callback"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def with_query(url, parameters):
    return url + ("&" if "?" in url else "?") + urlencode(parameters)


def http_client():
    ca_file = os.getenv("ARENA_OIDC_CA_FILE", "").strip()
    # Verification is never disabled: the ID token is trusted because of it.
    verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
    return httpx.Client(
        verify=verify,
        transport=transport,
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
    )


def fetch_json(method, url, **kwargs):
    try:
        with http_client() as client:
            response = client.request(method, url, **kwargs)
    except (httpx.HTTPError, OSError, ssl.SSLError) as error:
        raise LoginError("provider", f"{method} {url} failed: {error!r}") from error
    if response.status_code != 200:
        raise LoginError(
            "provider",
            f"{method} {url} returned HTTP {response.status_code}: "
            f"{response.text[:300]!r}",
        )
    try:
        data = response.json()
    except ValueError as error:
        raise LoginError("provider", f"{url} did not return JSON") from error
    if not isinstance(data, dict):
        raise LoginError("provider", f"{url} did not return a JSON object")
    return data


def discovery():
    """The issuer's discovery document, cached in memory."""
    expected = issuer()
    cached = _discovery.get(expected)
    if cached and cached[0] > time.time():
        return cached[1]
    if not expected.startswith("https://"):
        raise LoginError("provider", "ARENA_OIDC_ISSUER must be an https URL")
    meta = fetch_json("GET", expected + "/.well-known/openid-configuration")
    if meta.get("issuer") != expected:
        raise LoginError(
            "provider",
            f"Discovery issuer {meta.get('issuer')!r} does not match "
            f"ARENA_OIDC_ISSUER {expected!r}",
        )
    for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
        if not str(meta.get(key, "")).startswith("https://"):
            raise LoginError("provider", f"Discovery document lacks an https {key}")
    _discovery[expected] = (time.time() + DISCOVERY_SECONDS, meta)
    return meta


def safe_next(value, default="home"):
    """A same-site hash route (without `#`) for the post-login redirect."""
    route = (value or "").strip()
    route = route[1:] if route.startswith("#") else route
    if not NEXT_ROUTE.fullmatch(route) or re.match(r"login(\?|$)", route):
        return default
    return route


def error_location(code, linking=False):
    return (
        f"/#account/settings?sso_error={code}"
        if linking
        else f"/#login?sso_error={code}"
    )


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@router.get("/auth/oidc/login")
def oidc_login(
    request: Request,
    next_route: str = Query("", alias="next"),
    link: bool = False,
    db: DBSession = Depends(get_db),
):
    link_user = None
    if link:
        # Linking needs the browser session; SameSite=Strict keeps it from
        # being sent on navigations started by other sites.
        try:
            if request.headers.get("authorization"):
                raise HTTPException(403, "Browser session required")
            link_user = current_user(request, db)
        except HTTPException:
            return RedirectResponse(error_location("signin"), status_code=302)
    try:
        meta = discovery()
    except LoginError as error:
        log.warning("Keycloak sign-in is unavailable: %s", error)
        return RedirectResponse(
            error_location(error.code, bool(link_user)), status_code=302
        )
    db.execute(
        delete(OidcLoginAttempt).where(OidcLoginAttempt.expires_at < time.time())
    )
    pending = db.scalar(select(func.count()).select_from(OidcLoginAttempt))
    if pending >= MAX_PENDING_ATTEMPTS:
        db.commit()
        log.warning("Refusing Keycloak sign-in: %s attempts are pending", pending)
        return RedirectResponse(
            error_location("busy", bool(link_user)), status_code=302
        )
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    # Reuse this browser's binding so attempts in several tabs all stay valid.
    binding = request.cookies.get(BROWSER_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", binding):
        binding = secrets.token_urlsafe(32)
    db.add(
        OidcLoginAttempt(
            state_hash=digest(state),
            browser_hash=digest(binding),
            code_verifier=verifier,
            nonce=nonce,
            next_route=safe_next(next_route),
            link_user_id=link_user.id if link_user else None,
            expires_at=time.time() + ATTEMPT_SECONDS,
        )
    )
    db.commit()
    response = RedirectResponse(
        with_query(
            meta["authorization_endpoint"],
            {
                "response_type": "code",
                "client_id": client_id(),
                "redirect_uri": redirect_uri(request),
                "scope": SCOPE,
                "state": state,
                "nonce": nonce,
                "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
                "code_challenge_method": "S256",
            },
        ),
        status_code=302,
    )
    response.headers["Cache-Control"] = "no-store"
    # Lax, because Keycloak's redirect back may be a cross-site navigation.
    response.set_cookie(
        BROWSER_COOKIE,
        binding,
        max_age=ATTEMPT_SECONDS,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false") == "true",
        samesite="lax",
        path=COOKIE_PATH,
    )
    return response


def consume_attempt(db, request, state):
    """Delete and return the attempt for `state` as a dict; it works only once."""
    if not state:
        raise LoginError("state", "The callback has no state")
    key = digest(state)
    row = db.get(OidcLoginAttempt, key)
    if not row:
        raise LoginError("state", "Unknown, expired or already used state")
    attempt = {
        column.name: getattr(row, column.name)
        for column in OidcLoginAttempt.__table__.columns
    }
    # Deleting by key also makes concurrent callbacks with one state fail.
    deleted = db.execute(
        delete(OidcLoginAttempt).where(OidcLoginAttempt.state_hash == key)
    ).rowcount
    db.commit()
    if deleted != 1:
        raise LoginError("state", "State was used concurrently")
    binding = request.cookies.get(BROWSER_COOKIE, "")
    if not hmac.compare_digest(digest(binding), attempt["browser_hash"]):
        raise LoginError("state", "The callback came from a different browser")
    if attempt["expires_at"] < time.time():
        raise LoginError("expired", "The sign-in attempt expired")
    return attempt


def exchange_code(meta, code, verifier, redirect):
    # client_secret_basic: RFC 6749 2.3.1 form-encodes both parts first.
    tokens = fetch_json(
        "POST",
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "code_verifier": verifier,
        },
        auth=(quote_plus(client_id()), quote_plus(client_secret())),
        headers={"Accept": "application/json"},
    )
    if not isinstance(tokens.get("id_token"), str) or not isinstance(
        tokens.get("access_token"), str
    ):
        raise LoginError("token", "The token response lacks id_token or access_token")
    if str(tokens.get("token_type", "")).lower() != "bearer":
        raise LoginError("token", "The token response is not a bearer token")
    return tokens


def decode_segment(segment):
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_id_token(token, nonce):
    """Return the ID token claims after OpenID Connect Core 3.1.3.7 validation."""
    # Signature: Core 3.1.3.7 step 6 allows a client that receives the ID token
    # directly from the token endpoint over TLS to use TLS server validation in
    # place of checking the JWS signature. exchange_code() gets the token from
    # the discovered https token endpoint with certificate verification against
    # ARENA_OIDC_CA_FILE (never disabled), so the payload is only base64-decoded.
    # The image has no JOSE library. Never accept ID tokens from any other channel.
    parts = token.split(".")
    if len(parts) != 3:
        raise LoginError("token", "The ID token is not a compact JWS")
    try:
        header, claims = decode_segment(parts[0]), decode_segment(parts[1])
    except ValueError as error:
        raise LoginError("token", f"The ID token cannot be decoded: {error}") from error
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise LoginError("token", "The ID token is not a JSON object")
    if header.get("alg") in (None, "none"):
        raise LoginError("token", "The ID token is unsigned")
    if claims.get("iss") != issuer():
        raise LoginError("token", f"Unexpected issuer {claims.get('iss')!r}")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(audiences, list) or client_id() not in audiences:
        raise LoginError("token", f"Unexpected audience {audience!r}")
    if (len(audiences) > 1 or "azp" in claims) and claims.get("azp") != client_id():
        raise LoginError("token", f"Unexpected azp {claims.get('azp')!r}")
    current = time.time()
    if not number(claims.get("exp")) or claims["exp"] + CLOCK_SKEW < current:
        raise LoginError("token", "The ID token has expired")
    if not number(claims.get("iat")) or claims["iat"] - CLOCK_SKEW > current:
        raise LoginError("token", "The ID token was issued in the future")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(
        claims["nonce"].encode(), nonce.encode()
    ):
        raise LoginError("token", "The ID token nonce does not match")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not 0 < len(subject) <= 255:
        raise LoginError("token", "The ID token has no usable sub")
    return claims


def claim_text(claims, userinfo, key, limit):
    value = userinfo.get(key, claims.get(key))
    return value[:limit] if isinstance(value, str) else ""


def base_username(claim):
    name = re.sub(r"[^a-z0-9_]+", "_", claim.lower())
    name = re.sub(r"_+", "_", name).strip("_")[:USERNAME_MAX].strip("_")
    if len(name) >= 3:
        return name
    return f"{name}_user" if name else "user"


def provision_user(db, claim):
    """Create an SSO-only user named after `claim`, adding a number if taken."""
    base = base_username(claim)
    for count in range(1, 10000):
        suffix = str(count) if count > 1 else ""
        candidate = base[: USERNAME_MAX - len(suffix)] + suffix
        if db.scalar(select(User.id).where(User.username == candidate)):
            continue
        user = User(username=candidate, password_hash=unusable_password())
        try:
            with db.begin_nested():
                db.add(user)
        except IntegrityError:
            continue  # Taken concurrently.
        return user
    raise LoginError("account", f"No free username for {claim!r}")


def sync_role(db, user, claims, userinfo):
    """Set the role from Keycloak groups when group mapping is configured."""
    admin_groups = group_setting("ARENA_OIDC_ADMIN_GROUPS")
    host_groups = group_setting("ARENA_OIDC_HOST_GROUPS")
    sources = [
        source["groups"]
        for source in (claims, userinfo)
        if isinstance(source.get("groups"), list)
    ]
    if not (admin_groups or host_groups) or not sources:
        return
    groups = {
        group.strip().lstrip("/")
        for source in sources
        for group in source
        if isinstance(group, str)
    }
    role = (
        "admin" if groups & admin_groups else "host" if groups & host_groups else "user"
    )
    if role != user.role:
        record(
            db,
            None,
            "user.role",
            "user",
            user.id,
            {
                "username": user.username,
                "from": user.role,
                "to": role,
                "source": "oidc_groups",
            },
        )
        user.role = role


def resolve_user(db, attempt, claims, userinfo):
    provider, subject = issuer(), claims["sub"]
    email = claim_text(claims, userinfo, "email", 320)
    preferred = claim_text(claims, userinfo, "preferred_username", 255)
    identity = db.scalar(
        select(UserIdentity)
        .where(UserIdentity.provider == provider, UserIdentity.subject == subject)
        .with_for_update()
    )
    if attempt["link_user_id"] is not None:
        user = db.scalar(
            select(User).where(User.id == attempt["link_user_id"]).with_for_update()
        )
        if not user:
            raise LoginError("account", "The account being linked no longer exists")
        if identity and identity.user_id != user.id:
            raise LoginError(
                "linked",
                f"Subject {subject!r} is linked to user {identity.user_id}, "
                f"not {user.id}",
            )
        if not identity:
            if db.scalar(
                select(UserIdentity.id).where(
                    UserIdentity.provider == provider, UserIdentity.user_id == user.id
                )
            ):
                raise LoginError(
                    "link_exists",
                    f"User {user.id} is already linked to another subject",
                )
            identity = UserIdentity(provider=provider, subject=subject, user_id=user.id)
            record(
                db,
                user,
                "user.identity_link",
                "user",
                user.id,
                {
                    "username": user.username,
                    "provider": provider,
                    "subject": subject,
                    "email": email,
                },
            )
    elif identity:
        user = db.scalar(
            select(User).where(User.id == identity.user_id).with_for_update()
        )
        if not user:
            raise LoginError("account", f"Identity {identity.id} has no user")
    else:
        # Never match an existing account by name or email; see the module doc.
        user = provision_user(db, preferred or email.split("@")[0])
        identity = UserIdentity(provider=provider, subject=subject, user_id=user.id)
        record(
            db,
            None,
            "user.sso_create",
            "user",
            user.id,
            {
                "username": user.username,
                "provider": provider,
                "subject": subject,
                "preferred_username": preferred,
            },
        )
        db.add(
            ServiceNotice(
                user_id=user.id,
                title="Welcome to Arena",
                body="Your account was created when you signed in with Keycloak. Complete your profile and explore community work from the account menu.",
            )
        )
    if user.status == "suspended":
        raise LoginError("suspended", f"User {user.id} is suspended")
    db.add(identity)
    identity.email, identity.username_claim = email, preferred
    identity.last_login_at = now()
    sync_role(db, user, claims, userinfo)
    return user


@router.get("/auth/oidc/callback")
def oidc_callback(request: Request, db: DBSession = Depends(get_db)):
    params = request.query_params
    linking = False
    try:
        attempt = consume_attempt(db, request, params.get("state", ""))
        linking = attempt["link_user_id"] is not None
        if params.get("error"):
            raise LoginError(
                "denied",
                f"Keycloak returned {params.get('error')[:80]!r}: "
                f"{params.get('error_description', '')[:200]!r}",
            )
        if not params.get("code"):
            raise LoginError("denied", "The callback has no authorization code")
        meta = discovery()
        tokens = exchange_code(
            meta, params["code"], attempt["code_verifier"], redirect_uri(request)
        )
        claims = validate_id_token(tokens["id_token"], attempt["nonce"])
        userinfo = fetch_json(
            "GET",
            meta["userinfo_endpoint"],
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Accept": "application/json",
            },
        )
        if userinfo.get("sub") != claims["sub"]:
            raise LoginError("token", "The userinfo sub does not match the ID token")
        user = resolve_user(db, attempt, claims, userinfo)
        db.commit()
    except LoginError as error:
        db.rollback()
        log.warning("Keycloak sign-in failed (%s): %s", error.code, error)
        return RedirectResponse(error_location(error.code, linking), status_code=302)
    except Exception:
        db.rollback()
        log.exception("Keycloak sign-in failed unexpectedly")
        return RedirectResponse(error_location("failed", linking), status_code=302)
    if linking:
        # The user is already signed in; keep their current session.
        return RedirectResponse("/#account/settings?linked=1", status_code=302)
    response = RedirectResponse("/#" + attempt["next_route"], status_code=302)
    new_session(db, user, response, method="oidc")
    return response


def end_session_url(request):
    """The Keycloak logout URL for single sign-out, or None."""
    if not enabled():
        return None
    try:
        endpoint = discovery().get("end_session_endpoint")
    except LoginError as error:
        log.warning("Cannot end the Keycloak session: %s", error)
        return None
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        return None
    return with_query(
        endpoint,
        {
            "client_id": client_id(),
            "post_logout_redirect_uri": public_url(request) + "/",
        },
    )


def identity_json(row):
    return {
        "id": row.id,
        "provider": row.provider,
        "email": row.email,
        "username": row.username_claim,
        "created_at": row.created_at,
        "last_login_at": row.last_login_at,
    }


@router.get("/account/identities")
def identities(user=Depends(interactive_user), db: DBSession = Depends(get_db)):
    rows = db.scalars(
        select(UserIdentity)
        .where(UserIdentity.user_id == user.id)
        .order_by(UserIdentity.id)
    )
    return {
        "label": label(),
        "has_password": has_usable_password(user.password_hash),
        "identities": [identity_json(row) for row in rows],
    }


@router.delete("/account/identities/{id}", status_code=204)
def unlink_identity(
    id: int, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    db.refresh(user, with_for_update=True)
    row = db.get(UserIdentity, id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Linked account not found")
    if not has_usable_password(user.password_hash):
        raise HTTPException(
            409,
            "This account signs in only through Keycloak, so it cannot be unlinked",
        )
    if not setting(db, "local_login_enabled") and not is_admin(user):
        raise HTTPException(
            409,
            "Password sign-in is disabled on this site; unlinking would lock you out",
        )
    record(
        db,
        user,
        "user.identity_unlink",
        "user",
        user.id,
        {"username": user.username, "provider": row.provider, "subject": row.subject},
    )
    db.delete(row)
    db.commit()
