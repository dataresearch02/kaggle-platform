# Accounts and profile management

The header uses an avatar-only button. It opens a right-side account drawer with
Your work, Your profile, Your groups, Your API tokens, Settings and Log out.
Service notifications appear below these actions. Escape, the close button or
clicking the backdrop closes the drawer. Your work opens the existing work page.

## Profiles and settings

`#account/profile` edits display name, tagline, pronouns, occupation, organization,
location, website and biography. The account username remains the login identity.
PNG/JPEG profile photos are limited to 2 MB. Removing a photo restores the default
avatar. Details and photo bytes persist in PostgreSQL under the existing project
data bind mount, and are included in database backups.

`#profile/<username>` shows the public profile. Settings at `#account/settings`
can restrict the profile and photo to the owner. This does not change notebook,
dataset or group permissions. Changing the password requires the current password,
revokes all API tokens and other login sessions, and renews the current session.

## Groups

`#account/groups` supports creating and editing a group, joining by invite code,
viewing members, leaving, owner removal of members, rotating invite codes and
owner deletion. Invite codes are visible only to the owner. Rotating a code
invalidates the old code. The owner must delete a group instead of leaving it.
These groups organize membership; competition teams and content-sharing controls
remain separate. Group membership does not implicitly grant access to files.

## API tokens and command-line access

`#account/tokens` creates named tokens with read-only or read/write access and an
expiry of 1–365 days (the UI offers 7, 30, 90 or 365 days). Up to 25 tokens can be
retained per account. The complete token is returned only when created. Only its
SHA-256 hash and a short display prefix are stored. The list shows permissions,
expiry and last use; revocation takes effect for subsequent requests.

Set `ARENA_TOKEN` in your shell without committing it to files or source control.
For local testing:

```bash
curl -H "Authorization: Bearer $ARENA_TOKEN" \
  http://localhost:8080/api/work
```

Read/write credentials can call content APIs, with the same ownership and
competition-entry checks as browser requests. For example, save a private code
record from the command line:

```bash
curl -X POST -H "Authorization: Bearer $ARENA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"CLI experiment","code":"print(42)"}' \
  http://localhost:8080/api/notebooks
```

Bearer requests do not require the browser CSRF header. Browser-origin checks
still apply. Cookie-authenticated mutations still require `X-Arena-Client: web`.
Profile settings, group management and token management require a signed-in
browser session; tokens cannot mint additional credentials or change passwords.
Use HTTPS before exposing these credentials beyond the existing loopback setup.
There is no separate CLI package required; cURL and HTTP clients use these APIs.

## Service notifications

New accounts receive a stored welcome notification. Notifications may target one
user or all users, and read state persists per user. The drawer shows the latest
100 notifications. Ordinary users cannot publish service announcements.

An operator with API-container access can publish a service announcement:

```bash
docker compose exec api python -m app.service_notice \
  --title 'Scheduled maintenance' \
  --body 'Arena will be unavailable during the announced maintenance window.'
```

Add `--username <username>` to target a single account. Omitting it publishes to
all users, including accounts created later. The drawer refreshes notifications
when opened. This is an in-app service inbox; email and push delivery are not
implemented.
