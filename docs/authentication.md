# Authentication

Arena accounts can sign in two ways:

- **Local:** username and password (`POST /api/auth/login`), stored as scrypt hashes.
- **Keycloak:** OpenID Connect sign-in against the lab realm at `https://keycloak.ocp4.lab.local:9443/realms/ocp4`, which is backed by LDAP.

Both create the same Arena session cookie. Roles, suspension, API tokens and the audit log work the same way for both.

## How Keycloak sign-in works

1. The browser opens `GET /api/auth/oidc/login?next=<hash route>`. The API reads Keycloak's discovery document (`{issuer}/.well-known/openid-configuration`, cached in memory for an hour). It stores a single-use login attempt in `oidc_login_attempts` with the SHA-256 of `state`, the PKCE verifier, the `nonce`, the validated `next` route and an expiry 10 minutes out. It also sets a short-lived `arena_oidc` browser-binding cookie (HttpOnly, SameSite=Lax, path `/api/auth/oidc`) and redirects to Keycloak with `response_type=code`, `scope=openid profile email`, `state`, `nonce`, an S256 `code_challenge` and `redirect_uri=ARENA_PUBLIC_URL/api/auth/oidc/callback`.
2. The user signs in to Keycloak, which redirects to `GET /api/auth/oidc/callback?code=…&state=…`.
3. The API deletes the attempt, so a state works only once. It checks that the attempt has not expired and that the callback arrived in the browser that started it. It then exchanges the code at the token endpoint using `client_secret_basic` and the PKCE verifier.
4. The ID token claims are validated:
   - `iss` equals `ARENA_OIDC_ISSUER`.
   - `aud` contains `ARENA_OIDC_CLIENT_ID`. `azp` must equal the client id when there are several audiences or when `azp` is present.
   - `exp` and `iat` pass, allowing 60 seconds of clock skew.
   - `nonce` matches the stored attempt.
5. The API calls the userinfo endpoint with the access token and requires its `sub` to equal the ID token `sub`.
6. The Keycloak identity is looked up by (issuer, `sub`) in `user_identities`, creating an Arena user on first sign-in (below). Suspended accounts are refused. An Arena session is created and the browser goes to `/#<next>` (default `#home`).

Any failure redirects to `/#login?sso_error=<code>` (or `/#account/settings?sso_error=<code>` while linking) and logs the details on the API with the prefix `Keycloak sign-in failed`. The browser never sees tokens or provider error details.

Tokens are not stored. After the callback, Arena keeps only its own session cookie.

## Configuration

The API deployment already provides these variables. Keycloak sign-in is enabled only when the issuer, client id **and** client secret are all set. Otherwise every OIDC endpoint (`/api/auth/oidc/*`, `/api/account/identities*`) returns 404 and the UI shows no Keycloak button.

| Variable | Example | Purpose |
| --- | --- | --- |
| `ARENA_OIDC_ISSUER` | `https://keycloak.ocp4.lab.local:9443/realms/ocp4` | Realm issuer URL, without a trailing slash. Must be `https` and must match the discovery document's `issuer` exactly. |
| `ARENA_OIDC_CLIENT_ID` | `arena` | Keycloak client id |
| `ARENA_OIDC_CLIENT_SECRET` | from Secret `arena-oidc` | Client secret. Optional in the deployment; without it sign-in stays disabled. |
| `ARENA_OIDC_CA_FILE` | path to a PEM bundle | CA certificates that sign Keycloak's TLS certificate. The lab CA is not in the system trust store. When unset, the system trust store is used. Verification is never disabled. |
| `ARENA_PUBLIC_URL` | `https://arena.apps.ocp4.lab.local` | Builds `redirect_uri` and the post-logout redirect |
| `ARENA_OIDC_LABEL` | `Sign in with Keycloak` (default) | Button text |
| `ARENA_OIDC_ADMIN_GROUPS` | `arena-admins` | Optional comma-separated Keycloak groups that grant `admin` |
| `ARENA_OIDC_HOST_GROUPS` | `arena-hosts` | Optional comma-separated Keycloak groups that grant `host` |

All calls to Keycloak use `httpx` with a 5 second connect timeout and a 10 second overall timeout. They honor the standard `HTTPS_PROXY`/`NO_PROXY` variables, so keep `keycloak.ocp4.lab.local` in `NO_PROXY` if a cluster-wide proxy is configured.

## Keycloak client settings

In the Keycloak admin console, realm **ocp4** → **Clients** → **Create client**:

| Setting | Value |
| --- | --- |
| Client type | OpenID Connect |
| Client ID | `arena` |
| Client authentication | **On** (confidential client) |
| Authorization | Off |
| Authentication flow | **Standard flow only**: turn off Direct access grants, Implicit flow, Service accounts, OAuth 2.0 Device Authorization Grant and OIDC CIBA |
| Root URL / Home URL | `https://arena.apps.ocp4.lab.local` |
| Valid redirect URIs | `https://arena.apps.ocp4.lab.local/api/auth/oidc/callback` (exactly; no wildcards) |
| Valid post logout redirect URIs | `https://arena.apps.ocp4.lab.local/` |
| Web origins | `https://arena.apps.ocp4.lab.local` |
| Advanced → Proof Key for Code Exchange Code Challenge Method | **S256** |
| Credentials → Client Authenticator | Client Id and Secret |

Copy the secret from the **Credentials** tab.

The default client scopes `profile` and `email` supply `preferred_username` and `email`.

### Optional: groups for role sync

To manage Arena roles from Keycloak groups:

1. **Clients** → `arena` → **Client scopes** → `arena-dedicated` → **Add mapper** → **By configuration** → **Group Membership**.
2. Name `groups`, Token Claim Name `groups`, **Add to ID token** On, **Add to userinfo** On. Full group path may be on (`/arena-admins`) or off (`arena-admins`); Arena matches either.
3. Set `ARENA_OIDC_ADMIN_GROUPS` and/or `ARENA_OIDC_HOST_GROUPS` on the API deployment.

With group mapping configured and a `groups` claim present, every Keycloak sign-in sets the role:
- `admin` if the user is in any admin group;
- otherwise `host` if the user is in any host group;
- otherwise `user`.

Role changes are written to the audit log as `user.role` with `detail.source = "oidc_groups"`. If neither variable is set, or the token and userinfo carry no `groups` claim, roles are never changed. Note that a configured mapping also demotes manually promoted hosts and admins who are not in a mapped group.

## Enable it on the cluster

```bash
oc create secret generic arena-oidc -n arena \
  --from-literal=ARENA_OIDC_CLIENT_SECRET='<secret from the Credentials tab>'
oc rollout restart deployment/api -n arena
```

Then check `https://arena.apps.ocp4.lab.local/api/site`: `oidc_enabled` should be `true`. To rotate the secret, regenerate it in Keycloak, then replace the Secret (`oc delete secret arena-oidc -n arena` and create it again) and restart the API deployment.

## Accounts and linking

- **First Keycloak sign-in** with an unknown (issuer, `sub`) creates a **new** Arena user, even while `registration_open` is `false`. The username comes from `preferred_username` (or the email local part), lowercased, with characters outside `[a-z0-9_]` replaced by `_` and truncated to 40 characters. A number is appended if the name is taken (`jdoe`, `jdoe2`, …). The account has no usable local password; its `password_hash` holds an unusable marker that local sign-in always rejects. The audit log records `user.sso_create`.
- **No automatic linking.** Arena never matches a Keycloak user to an existing account by username or email. Anyone can register a local account with any free name, so matching would hand that account to whoever holds the same name in Keycloak, or the reverse. A local `jdoe` and Keycloak `jdoe` therefore become `jdoe` and `jdoe2` unless the local user links explicitly.
- **Explicit linking.** A signed-in local user opens **Settings** → **Keycloak sign-in** → **Link Keycloak account** (`GET /api/auth/oidc/login?link=1`). After the Keycloak sign-in, that identity is attached to the signed-in account (`user.identity_link`). The link is refused if that Keycloak account is already linked to another Arena user, or if this Arena user already has a different Keycloak account linked.
- **Unlinking** (`user.identity_unlink`) is allowed only when the account still has a local password. When `local_login_enabled` is `false` it is also refused for non-administrators, because they would be locked out.
- **SSO-only accounts** cannot use **Change password** (the API returns 409); Settings says the password is managed in Keycloak. An administrator's **Reset password** gives such an account a local password.
- Suspended users are refused at the callback with `sso_error=suspended`.

`GET /api/auth/me` includes `has_password`. `GET /api/account/identities` returns `{label, has_password, identities: [{id, provider, email, username, created_at, last_login_at}]}`, and `DELETE /api/account/identities/{id}` unlinks. Both require a browser session.

## Local sign-in and break-glass

`GET /api/site` includes `oidc_enabled` and `oidc_label`. When Keycloak is enabled and the site setting `local_login_enabled` is `false`, the sign-in dialog shows only the Keycloak button and hides the password form and registration. The API still refuses local sign-in for everyone except administrators. Administrators can reach the password form at:

```
https://arena.apps.ocp4.lab.local/#login?local=1
```

Keep at least one local administrator with a password so the site stays manageable if Keycloak is unavailable.

## Logout

`POST /api/auth/logout` always deletes the Arena session. If the session was created by Keycloak sign-in and the discovery document advertises `end_session_endpoint`, the response is `200 {"end_session_url": …}`, and the web app navigates there with `client_id=arena` and `post_logout_redirect_uri=https://arena.apps.ocp4.lab.local/`. Because Arena does not keep ID tokens, no `id_token_hint` is sent. Keycloak may therefore ask the user to confirm the logout. Local sessions still get `204`.

## Security notes

- **ID token signature.** Arena has no JOSE/JWT library. It relies on OpenID Connect Core 3.1.3.7 step 6: an ID token received directly from the token endpoint over TLS may be validated by TLS server authentication instead of its JWS signature. The token endpoint must be `https`, and the call verifies Keycloak's certificate against `ARENA_OIDC_CA_FILE` with verification never disabled. The payload is only base64-decoded; tokens with `alg: none` are rejected. ID tokens are never accepted from the browser or any other channel.
- **State, nonce and PKCE.** Each attempt has random `state`, `nonce` and a PKCE S256 verifier. Only the state's hash is stored, attempts are deleted when used and expire after 10 minutes, and at most 5000 may be pending.
- **Login and link CSRF.** The browser-binding cookie ties an attempt to the browser that started it, so a Keycloak link sent to someone else cannot sign them in or link their Keycloak account to the sender's Arena account. Linking requires the SameSite=Strict session cookie when the attempt starts.
- **Redirects.** `next` must be a hash route (a letter or digit first, then letters, digits, `_`, `-`, `/` and an optional simple query). Anything else, including URLs, `//host` and `#login`, becomes `#home`. Redirects are always relative (`/#…`).
- **Identity matching** uses only (issuer, `sub`). `email` and `preferred_username` are informational copies.

## Troubleshooting

API logs: `oc logs deployment/api -n arena | grep -i keycloak`.

| Symptom (`sso_error`) | Cause and fix |
| --- | --- |
| No Keycloak button; `/api/site` shows `oidc_enabled: false` | One of `ARENA_OIDC_ISSUER`, `ARENA_OIDC_CLIENT_ID`, `ARENA_OIDC_CLIENT_SECRET` is missing. Check `oc get secret arena-oidc -n arena` and restart the API. |
| `provider` with `CERTIFICATE_VERIFY_FAILED` | `ARENA_OIDC_CA_FILE` is unset, unreadable or lacks the CA that signed Keycloak's certificate. Mount the lab CA PEM bundle. |
| `provider` with `Discovery issuer … does not match` | `ARENA_OIDC_ISSUER` must equal Keycloak's issuer exactly: scheme, host, port `:9443` and realm path, without a trailing slash. Check Keycloak's frontend URL/hostname settings. |
| `provider` with `ConnectError` or a timeout | Keycloak is unreachable from the pod. Check DNS, NetworkPolicy/egress and `NO_PROXY`. |
| `provider` with `token … returned HTTP 401` (`unauthorized_client`, `invalid_client`) | Wrong client secret, or client authentication is off. Recreate the Secret and restart. |
| `provider` with `HTTP 400` (`invalid_grant`, `Code not valid`, PKCE errors) | The code was reused or expired, `redirect_uri` differs from the one used at login (check `ARENA_PUBLIC_URL`), or the PKCE method is not S256. |
| Keycloak page "Invalid parameter: redirect_uri" | Valid redirect URIs must contain exactly `https://arena.apps.ocp4.lab.local/api/auth/oidc/callback`, and `ARENA_PUBLIC_URL` must match. |
| `state` | The attempt was already used, or the callback opened in another browser/profile, or cookies are blocked. Start again from Arena, not from a bookmarked Keycloak URL. |
| `expired` | More than 10 minutes passed on the Keycloak page. |
| `token` with `expired` or `issued in the future` | The API node's clock differs from Keycloak's by more than a minute. Check NTP. |
| `token` with `Unexpected audience`/`azp` | The token was issued for another client. Check the client id. |
| `denied` | The user cancelled, or Keycloak refused consent or login. |
| `suspended` | The Arena account is suspended; an administrator can reactivate it. |
| `linked` / `link_exists` | That Keycloak account belongs to another Arena user, or this user already has one linked. Unlink the existing link first. |
| Roles never change | Group mapping variables are unset, or the `groups` mapper is not added to the ID token or userinfo. |
| Logout asks for confirmation on Keycloak | Expected without `id_token_hint`; confirm to end the Keycloak session. |
