"""Keycloak (OpenID Connect) sign-in against a fake identity provider; no network."""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import oidc
from app.auth import verify_password
from app.db import get_db
from app.main import app
from app.models import AuditLog, OidcLoginAttempt, Session, User, UserIdentity

ISSUER = "https://keycloak.test/realms/lab"
PUBLIC_URL = "https://arena.test"
REDIRECT = PUBLIC_URL + "/api/auth/oidc/callback"
SECRET = "s3cret value"
PASSWORD = "good-password-123"
SETTINGS = (
    "ARENA_OIDC_ISSUER",
    "ARENA_OIDC_CLIENT_ID",
    "ARENA_OIDC_CLIENT_SECRET",
    "ARENA_OIDC_CA_FILE",
    "ARENA_OIDC_LABEL",
    "ARENA_OIDC_ADMIN_GROUPS",
    "ARENA_OIDC_HOST_GROUPS",
    "ARENA_PUBLIC_URL",
)


def database():
    return next(app.dependency_overrides[get_db]())


def browser():
    return TestClient(app, headers={"X-Arena-Client": "web"})


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(claims, alg="RS256"):
    header = json.dumps({"alg": alg, "typ": "JWT", "kid": "test"}).encode()
    return f"{b64url(header)}.{b64url(json.dumps(claims).encode())}.c2lnbmF0dXJl"


def actions(action):
    with database() as db:
        return list(
            db.scalars(
                select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
            )
        )


class FakeKeycloak:
    """Discovery, token and userinfo endpoints served through httpx.MockTransport."""

    def __init__(self):
        self.subject = "5b1e-alice"
        self.username = "alice"
        self.email = "alice@example.test"
        self.groups = None
        self.claims = {}
        self.userinfo = {}
        self.alg = "RS256"
        self.discovery_issuer = ISSUER
        self.pending = {}

    def __call__(self, request):
        base = ISSUER + "/protocol/openid-connect"
        if str(request.url) == ISSUER + "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": self.discovery_issuer,
                    "authorization_endpoint": base + "/auth",
                    "token_endpoint": base + "/token",
                    "userinfo_endpoint": base + "/userinfo",
                    "end_session_endpoint": base + "/logout",
                },
            )
        if str(request.url) == base + "/token":
            # client_secret_basic with form-encoded credentials.
            expected = base64.b64encode(b"arena:s3cret+value").decode()
            assert request.headers["authorization"] == "Basic " + expected
            form = parse_qs(request.content.decode())
            nonce, challenge = self.pending.pop(form["code"][0])
            verifier = form["code_verifier"][0].encode()
            assert b64url(hashlib.sha256(verifier).digest()) == challenge
            assert form["redirect_uri"] == [REDIRECT]
            assert form["grant_type"] == ["authorization_code"]
            claims = {
                "iss": ISSUER,
                "aud": "arena",
                "azp": "arena",
                "sub": self.subject,
                "exp": time.time() + 300,
                "iat": time.time(),
                "nonce": nonce,
                "preferred_username": self.username,
                "email": self.email,
            }
            if self.groups is not None:
                claims["groups"] = self.groups
            claims.update(self.claims)
            return httpx.Response(
                200,
                json={
                    "access_token": "access-" + form["code"][0],
                    "token_type": "Bearer",
                    "id_token": jwt(claims, self.alg),
                },
            )
        if str(request.url) == base + "/userinfo":
            assert request.headers["authorization"].startswith("Bearer access-")
            info = {"sub": self.subject, "preferred_username": self.username}
            info.update(self.userinfo)
            return httpx.Response(200, json=info)
        return httpx.Response(404)


@pytest.fixture
def idp(client, monkeypatch):
    fake = FakeKeycloak()
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARENA_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("ARENA_OIDC_CLIENT_ID", "arena")
    monkeypatch.setenv("ARENA_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("ARENA_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setattr(oidc, "transport", httpx.MockTransport(fake))
    monkeypatch.setattr(oidc, "_discovery", {})
    return fake


def authorize(client, **params):
    start = client.get("/api/auth/oidc/login", params=params, follow_redirects=False)
    assert start.status_code == 302, start.text
    query = parse_qs(urlsplit(start.headers["location"]).query)
    return start, {key: values[0] for key, values in query.items()}


def callback(client, idp, query, **params):
    code = secrets.token_urlsafe(8)
    idp.pending[code] = (query["nonce"], query["code_challenge"])
    response = client.get(
        "/api/auth/oidc/callback",
        params={"code": code, "state": query["state"], **params},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response.headers["location"]


def sign_in(client, idp, **params):
    _, query = authorize(client, **params)
    return callback(client, idp, query)


def register(username):
    client = browser()
    response = client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return client


def test_disabled_without_complete_configuration(client, monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARENA_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("ARENA_OIDC_CLIENT_ID", "arena")  # No client secret.
    for path in (
        "/api/auth/oidc/login",
        "/api/auth/oidc/login?link=1",
        "/api/auth/oidc/callback?state=x&code=y",
        "/api/account/identities",
    ):
        assert client.get(path, follow_redirects=False).status_code == 404
    assert client.delete("/api/account/identities/1").status_code == 404
    site = client.get("/api/site").json()
    assert site["oidc_enabled"] is False
    assert site["oidc_label"] == "Sign in with Keycloak"


def test_login_redirect_carries_state_nonce_and_pkce(client, idp, monkeypatch):
    monkeypatch.setenv("ARENA_OIDC_LABEL", "Sign in with Lab SSO")
    assert client.get("/api/site").json()["oidc_enabled"] is True
    assert client.get("/api/site").json()["oidc_label"] == "Sign in with Lab SSO"
    start, query = authorize(client, next="#competitions/1/overview")
    location = start.headers["location"]
    assert location.startswith(ISSUER + "/protocol/openid-connect/auth?")
    assert query["response_type"] == "code"
    assert query["client_id"] == "arena"
    assert query["redirect_uri"] == REDIRECT
    assert query["scope"] == "openid profile email"
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43
    assert len(query["state"]) >= 43 and len(query["nonce"]) >= 43
    cookie = start.headers["set-cookie"].lower()
    assert "arena_oidc=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    with database() as db:
        [row] = db.scalars(select(OidcLoginAttempt)).all()
        # Only the state's hash is stored.
        assert row.state_hash == hashlib.sha256(query["state"].encode()).hexdigest()
        verifier = row.code_verifier.encode()
        assert b64url(hashlib.sha256(verifier).digest()) == query["code_challenge"]
        assert row.nonce == query["nonce"]
        assert row.next_route == "competitions/1/overview"
        assert row.link_user_id is None
        assert 590 < row.expires_at - time.time() <= 600


def test_callback_creates_and_then_reuses_the_user(client, idp):
    assert sign_in(client, idp, next="competitions/1/overview") == (
        "/#competitions/1/overview"
    )
    me = client.get("/api/auth/me").json()
    assert (me["username"], me["role"], me["has_password"]) == ("alice", "user", False)
    with database() as db:
        [identity] = db.scalars(select(UserIdentity)).all()
        assert (identity.provider, identity.subject, identity.user_id) == (
            ISSUER,
            idp.subject,
            me["id"],
        )
        assert (identity.email, identity.username_claim) == (idp.email, "alice")
        assert identity.last_login_at
        assert db.scalar(select(Session.auth_method)) == "oidc"
        assert not db.scalars(select(OidcLoginAttempt)).all()
    [created] = actions("user.sso_create")
    assert created.actor_id is None
    assert json.loads(created.detail)["subject"] == idp.subject

    # A second sign-in, with a changed username claim, reaches the same account.
    idp.username = "alice_renamed"
    other = browser()
    assert sign_in(other, idp) == "/#home"
    assert other.get("/api/auth/me").json()["id"] == me["id"]
    with database() as db:
        assert len(db.scalars(select(UserIdentity)).all()) == 1
        assert db.scalar(select(UserIdentity.username_claim)) == "alice_renamed"
        assert not db.scalar(select(User).where(User.username == "alice_renamed"))

    # Logout of an SSO session also returns the Keycloak end-session URL.
    logout = other.post("/api/auth/logout")
    assert logout.status_code == 200
    url = urlsplit(logout.json()["end_session_url"])
    assert url.geturl().startswith(ISSUER + "/protocol/openid-connect/logout?")
    assert parse_qs(url.query) == {
        "client_id": ["arena"],
        "post_logout_redirect_uri": [PUBLIC_URL + "/"],
    }
    assert other.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200
    local = register("local_member")
    assert local.post("/api/auth/logout").status_code == 204


def test_state_is_single_use_browser_bound_and_expires(client, idp):
    _, query = authorize(client)
    assert callback(client, idp, query) == "/#home"
    assert callback(client, idp, query) == "/#login?sso_error=state"
    unknown = client.get(
        "/api/auth/oidc/callback",
        params={"state": "unknown", "code": "x"},
        follow_redirects=False,
    )
    assert unknown.headers["location"] == "/#login?sso_error=state"
    assert (
        client.get("/api/auth/oidc/callback", follow_redirects=False).headers[
            "location"
        ]
        == "/#login?sso_error=state"
    )

    # A state sent to another browser (login CSRF) does not sign that browser in.
    _, query = authorize(client)
    stranger = browser()
    assert callback(stranger, idp, query) == "/#login?sso_error=state"
    assert stranger.get("/api/auth/me").status_code == 401
    assert callback(client, idp, query) == "/#login?sso_error=state"

    _, query = authorize(client)
    with database() as db:
        key = hashlib.sha256(query["state"].encode()).hexdigest()
        db.get(OidcLoginAttempt, key).expires_at = time.time() - 1
        db.commit()
    assert callback(client, idp, query) == "/#login?sso_error=expired"

    _, query = authorize(client)
    denied = client.get(
        "/api/auth/oidc/callback",
        params={"state": query["state"], "error": "access_denied"},
        follow_redirects=False,
    )
    assert denied.headers["location"] == "/#login?sso_error=denied"


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.test/realms/lab"},
        {"aud": "another-client", "azp": "another-client"},
        {"aud": ["another-client", "arena"], "azp": "another-client"},
        {"aud": ["another-client", "arena"], "azp": None},
        {"nonce": "replayed-nonce"},
        {"exp": time.time() - 3600},
        {"iat": time.time() + 3600},
        {"sub": ""},
    ],
)
def test_invalid_id_tokens_are_rejected(client, idp, claims):
    idp.claims = claims
    assert sign_in(client, idp) == "/#login?sso_error=token"
    assert client.get("/api/auth/me").status_code == 401
    with database() as db:
        assert not db.scalars(select(UserIdentity)).all()
        assert not db.scalar(select(User).where(User.username == "alice"))


def test_multiple_audiences_with_matching_azp_are_accepted(client, idp):
    idp.claims = {"aud": ["account", "arena"], "azp": "arena"}
    assert sign_in(client, idp) == "/#home"


def test_userinfo_subject_mismatch_and_unsigned_tokens_are_rejected(client, idp):
    idp.userinfo = {"sub": "someone-else"}
    assert sign_in(client, idp) == "/#login?sso_error=token"
    idp.userinfo = {}
    idp.alg = "none"
    assert sign_in(client, idp) == "/#login?sso_error=token"
    assert client.get("/api/auth/me").status_code == 401
    with database() as db:
        assert not db.scalars(select(UserIdentity)).all()


def test_discovery_issuer_must_match(client, idp):
    idp.discovery_issuer = "https://keycloak.test/realms/other"
    assert authorize(client)[0].headers["location"] == "/#login?sso_error=provider"


def test_suspended_user_is_refused(client, idp):
    assert sign_in(client, idp) == "/#home"
    with database() as db:
        db.scalar(select(User).where(User.username == "alice")).status = "suspended"
        db.commit()
    fresh = browser()
    assert sign_in(fresh, idp) == "/#login?sso_error=suspended"
    assert fresh.get("/api/auth/me").status_code == 401


def test_no_automatic_linking_to_a_local_account(member, idp):
    idp.username = "learner"
    idp.email = "learner@example.test"
    other = browser()
    assert sign_in(other, idp) == "/#home"
    me = other.get("/api/auth/me").json()
    assert me["username"] == "learner2" and me["has_password"] is False
    assert member.get("/api/auth/me").json()["username"] == "learner"
    assert member.get("/api/account/identities").json()["identities"] == []

    # Claims are sanitized to the username rule.
    idp.subject, idp.username = "5b1e-jane", "Jane.Doe@corp"
    jane = browser()
    assert sign_in(jane, idp) == "/#home"
    assert jane.get("/api/auth/me").json()["username"] == "jane_doe_corp"
    idp.subject, idp.username = "5b1e-long", "x" * 60
    long_name = browser()
    sign_in(long_name, idp)
    assert long_name.get("/api/auth/me").json()["username"] == "x" * 40


def test_explicit_linking_and_double_linking(member, idp):
    anonymous = browser().get("/api/auth/oidc/login?link=1", follow_redirects=False)
    assert anonymous.headers["location"] == "/#login?sso_error=signin"

    _, query = authorize(member, link="1", next="https://evil.test")
    assert callback(member, idp, query) == "/#account/settings?linked=1"
    listing = member.get("/api/account/identities").json()
    assert listing["has_password"] is True
    [identity] = listing["identities"]
    assert (identity["username"], identity["provider"]) == ("alice", ISSUER)
    [linked] = actions("user.identity_link")
    assert json.loads(linked.detail)["username"] == "learner"

    # Keycloak sign-in now reaches the linked local account.
    fresh = browser()
    assert sign_in(fresh, idp) == "/#home"
    assert fresh.get("/api/auth/me").json()["username"] == "learner"

    # The same Keycloak account cannot be linked to another Arena account.
    other = register("other_member")
    _, query = authorize(other, link="1")
    assert callback(other, idp, query) == "/#account/settings?sso_error=linked"
    assert other.get("/api/account/identities").json()["identities"] == []

    # A second Keycloak account cannot be linked to the same Arena account.
    idp.subject = "5b1e-second"
    _, query = authorize(member, link="1")
    assert callback(member, idp, query) == "/#account/settings?sso_error=link_exists"

    # Unlinking works while the account has a local password.
    assert other.delete(f"/api/account/identities/{identity['id']}").status_code == 404
    assert member.delete(f"/api/account/identities/{identity['id']}").status_code == 204
    assert member.get("/api/account/identities").json()["identities"] == []
    assert len(actions("user.identity_unlink")) == 1


def test_sso_only_accounts_have_no_local_password(client, idp):
    assert sign_in(client, idp) == "/#home"
    listing = client.get("/api/account/identities").json()
    assert listing["has_password"] is False
    [identity] = listing["identities"]
    unlink = client.delete(f"/api/account/identities/{identity['id']}")
    assert unlink.status_code == 409
    change = client.put(
        "/api/account/password",
        json={"current_password": "anything-at-all", "new_password": PASSWORD},
    )
    assert change.status_code == 409
    with database() as db:
        stored = db.scalar(select(User.password_hash).where(User.username == "alice"))
    for password in (PASSWORD, stored, "0" * 32, "!" * 12):
        login = browser().post(
            "/api/auth/login", json={"username": "alice", "password": password}
        )
        assert login.status_code == 401
    for bad in (stored, "", "!", "no-colon", "a:b:c", "!salt:digest"):
        assert verify_password("anything-at-all", bad) is False


def test_groups_set_roles_with_audit_entries(client, idp, monkeypatch):
    def role():
        fresh = browser()
        assert sign_in(fresh, idp) == "/#home"
        return fresh.get("/api/auth/me").json()["role"]

    # Without group settings a groups claim never changes roles.
    idp.groups = ["/arena-admins"]
    assert role() == "user"
    monkeypatch.setenv("ARENA_OIDC_ADMIN_GROUPS", "arena-admins, /platform/owners")
    monkeypatch.setenv("ARENA_OIDC_HOST_GROUPS", "arena-hosts")
    assert role() == "admin"
    idp.groups = ["arena-hosts", "/staff"]
    assert role() == "host"
    idp.groups = None
    idp.userinfo = {"groups": ["/platform/owners"]}
    assert role() == "admin"
    idp.userinfo = {}
    assert role() == "admin"  # No groups claim: the role is left unchanged.
    idp.groups = []
    assert role() == "user"
    entries = actions("user.role")
    assert all(entry.actor_id is None for entry in entries)
    assert [
        (detail["from"], detail["to"], detail["source"])
        for detail in (json.loads(entry.detail) for entry in entries)
    ] == [
        ("user", "admin", "oidc_groups"),
        ("admin", "host", "oidc_groups"),
        ("host", "admin", "oidc_groups"),
        ("admin", "user", "oidc_groups"),
    ]


def test_next_cannot_redirect_off_site(client, idp):
    for value in (
        "https://evil.test/",
        "//evil.test",
        "/\\evil.test",
        "#//evil.test",
        "javascript:alert(1)",
        "%2F%2Fevil.test",
        "home\r\nLocation: https://evil.test",
        "login?sso_error=token",
        "a" * 300,
        "",
    ):
        assert sign_in(browser(), idp, next=value) == "/#home", value
    assert sign_in(browser(), idp, next="#discussions/7") == "/#discussions/7"
    assert sign_in(browser(), idp, next="code?tab=mine") == "/#code?tab=mine"


def test_local_login_setting_with_keycloak(client, idp):
    learner = register("learner")
    chief = register("chief")
    with database() as db:
        db.scalar(select(User).where(User.username == "chief")).role = "admin"
        db.commit()
    settings = chief.put(
        "/api/admin/settings",
        json={"local_login_enabled": False, "registration_open": False},
    )
    assert settings.status_code == 200
    site = browser().get("/api/site").json()
    assert site["local_login_enabled"] is False and site["oidc_enabled"] is True

    def login(username):
        return browser().post(
            "/api/auth/login", json={"username": username, "password": PASSWORD}
        )

    assert login("learner").status_code == 403
    assert login("chief").status_code == 200
    # Keycloak sign-in still provisions accounts while registration is closed.
    assert sign_in(browser(), idp) == "/#home"

    # Unlinking would lock a non-administrator out while local sign-in is off.
    idp.subject = "5b1e-learner"
    _, query = authorize(learner, link="1")
    assert callback(learner, idp, query) == "/#account/settings?linked=1"
    [identity] = learner.get("/api/account/identities").json()["identities"]
    assert learner.delete(f"/api/account/identities/{identity['id']}").status_code == (
        409
    )
