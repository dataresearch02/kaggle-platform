"""Authenticate Hub users with the existing, server-verified Arena session."""

import json
import os
from urllib.parse import unquote, urlsplit

from jupyterhub.auth import Authenticator
from jupyterhub.handlers.base import BaseHandler
from jupyterhub.utils import url_path_join
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.web import HTTPError


class ArenaLoginHandler(BaseHandler):
    async def get(self):
        # Always verify Arena, even if a different Hub account has a stale cookie.
        user = await self.login_user()
        if user is None:
            raise HTTPError(403, "Sign in to Arena, then reopen your notebook.")
        target = self.get_argument("next", f"/jupyter/user/{user.name}/lab")
        path = unquote(urlsplit(target).path)
        own = f"/jupyter/user/{user.name}/"
        oauth = "/jupyter/hub/api/oauth2/authorize"
        if (
            not target.startswith("/jupyter/")
            or "\\" in target
            or urlsplit(target).netloc
            or any(p in (".", "..") for p in path.split("/"))
            or not (path.startswith(own) or path == oauth)
        ):
            target = f"{own}lab"
        self.redirect(target)


class ArenaAuthenticator(Authenticator):
    auto_login = True
    allow_all = True

    def login_url(self, base_url):
        return url_path_join(base_url, "arena-login")

    def get_handlers(self, app):
        return [(r"/arena-login", ArenaLoginHandler)]

    async def authenticate(self, handler, data=None):
        cookie = handler.get_cookie("arena_session")
        if not cookie:
            return None
        response = await AsyncHTTPClient().fetch(
            HTTPRequest(
                os.environ["ARENA_API_URL"].rstrip("/") + "/auth/me",
                headers={"Cookie": f"arena_session={cookie}"},
                request_timeout=10,
            ),
            raise_error=False,
        )
        if response.code == 401:
            return None
        if response.code != 200:
            raise HTTPError(503, "Arena authentication is temporarily unavailable")
        identity = json.loads(response.body)
        return {"name": f"arena-{int(identity['id'])}", "admin": False}
