import { useEffect, useState } from 'react';
import { api, oidcLoginPath, ssoErrorMessage, type User, type CompetitionResult } from './api';
import { Avatar, type Profile } from './AccountMenu';
import { MedalBadge } from './CompetitionRules';
import ModerationActions, { HiddenNotice } from './Moderation';

type Token = {
  id: number;
  name: string;
  prefix: string;
  scope: string;
  expires_at: number;
  created_at: string;
  last_used_at: string | null;
};
type Group = {
  id: number;
  name: string;
  description: string;
  owner_id: number;
  invite_code: string | null;
  members: User[];
};
type Identities = {
  label: string;
  has_password: boolean;
  identities: {
    id: number;
    provider: string;
    email: string;
    username: string;
    created_at: string;
    last_login_at: string | null;
  }[];
};
/** The result of returning from Keycloak account linking, if any. */
function linkResultFromHash() {
  const match = window.location.hash.match(/^#account\/settings\?(.*)$/);
  const parameters = new URLSearchParams(match?.[1] || '');
  const code = parameters.get('sso_error');
  if (code) return { error: true, text: ssoErrorMessage(code) };
  return parameters.get('linked') === '1' ? { error: false, text: 'Keycloak account linked' } : null;
}
export function accountRouteFromHash() {
  // Keycloak linking returns with a query such as ?linked=1.
  const path = window.location.hash.slice(1).replace(/\?[\w=&.-]*$/, '');
  return /^(account\/(profile|groups|tokens|settings)|profile\/[a-zA-Z0-9_]+)$/.test(path)
    ? path
    : null;
}
export default function AccountPage({
  route,
  user,
  updated,
  signIn,
}: {
  route: string;
  user: User | null;
  updated: () => void;
  signIn: () => void;
}) {
  const publicView = route.startsWith('profile/');
  const section = route.split('/')[1];
  const [profile, setProfile] = useState<Profile | null>(null);
  const [results, setResults] = useState<CompetitionResult[]>([]);
  const [tokens, setTokens] = useState<Token[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [secret, setSecret] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  // Null while Keycloak sign-in is not configured (the endpoint returns 404).
  const [identities, setIdentities] = useState<Identities | null>(null);
  const [linkResult] = useState(linkResultFromHash);
  useEffect(() => {
    if (linkResult) history.replaceState(null, '', '#account/settings');
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    if (!user && !publicView) {
      setLoading(false);
      return;
    }
    setResults([]);
    if (publicView)
      api<CompetitionResult[]>(`/profiles/${section}/competitions`)
        .then((rows) => {
          if (active) setResults(rows);
        })
        .catch(() => {
          if (active) setResults([]);
        });
    const request = publicView
      ? api<Profile>(`/profiles/${section}`).then((row) => {
          if (active) setProfile(row);
        })
      : section === 'groups'
        ? api<Group[]>('/account/groups').then((rows) => {
            if (active) setGroups(rows);
          })
        : section === 'tokens'
          ? api<Token[]>('/account/tokens').then((rows) => {
              if (active) setTokens(rows);
            })
          : api<Profile>('/account/profile').then((row) => {
              if (active) setProfile(row);
            });
    if (!publicView && section === 'settings')
      api<Identities>('/account/identities')
        .then((row) => {
          if (active) setIdentities(row);
        })
        .catch(() => {
          if (active) setIdentities(null);
        });
    request
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [route, user?.id]);
  async function run(action: () => Promise<void>, message: string) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
      setNotice(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const groupRefresh = async () => setGroups(await api<Group[]>('/account/groups'));
  const tokenRefresh = async () => setTokens(await api<Token[]>('/account/tokens'));
  if (!user && !publicView)
    return (
      <section className="account-page">
        <h1>Your account</h1>
        <p>Sign in to manage your account.</p>
        <button className="button" onClick={signIn}>
          Sign in
        </button>
      </section>
    );
  return (
    <section className="account-page">
      <header className="account-page-heading">
        <div>
          <span className="eyebrow">{publicView ? 'COMMUNITY' : 'YOUR ACCOUNT'}</span>
          <h1>
            {publicView
              ? profile?.display_name || section
              : (
                  {
                    profile: 'Your profile',
                    groups: 'Your groups',
                    tokens: 'Your API tokens',
                    settings: 'Settings',
                  } as Record<string, string>
                )[section]}
          </h1>
        </div>
        {!publicView && section === 'profile' && user && (
          <a className="button secondary" href={`#profile/${user.username}`}>
            View your public profile
          </a>
        )}
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
      {loading ? (
        <p role="status">Loading account…</p>
      ) : (
        <>
          {publicView && profile && (
            <article className="account-card public-profile">
              <Avatar profile={profile} />
              <h2>{profile.display_name || profile.username}</h2>
              <p>
                @{profile.username} · Joined {new Date(profile.joined_at).toLocaleDateString()}
              </p>
              <p>{profile.tagline}</p>
              <p>
                {[profile.occupation, profile.organization, profile.location, profile.pronouns]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              <p className="profile-bio">{profile.bio}</p>
              <HiddenNotice hidden={profile.hidden} reason={profile.hidden_reason} />
              {profile.id !== undefined && (
                <ModerationActions
                  kind="profile"
                  id={profile.id}
                  ownerId={profile.id}
                  hidden={profile.hidden}
                  user={user}
                  signIn={signIn}
                  label="profile"
                  onChange={(change) =>
                    setProfile(
                      change.deleted
                        ? {
                            ...profile,
                            display_name: '',
                            tagline: '',
                            pronouns: '',
                            occupation: '',
                            organization: '',
                            location: '',
                            bio: '',
                            website: null,
                            has_custom_avatar: false,
                          }
                        : { ...profile, hidden: change.hidden, hidden_reason: change.reason },
                    )
                  }
                />
              )}
              {profile.website && (
                <a href={profile.website} target="_blank" rel="noreferrer">
                  Website ↗
                </a>
              )}
              {user?.username === profile.username && (
                <p>
                  <a href="#account/profile">Edit your profile</a>
                </p>
              )}
            </article>
          )}
          {publicView && profile && (
            <section className="account-card profile-results">
              <h2>Competition results</h2>
              {results.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Competition</th>
                        <th>Final rank</th>
                        <th>Medal</th>
                        <th>Team</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((row) => (
                        <tr key={row.competition_id}>
                          <td>
                            <a href={`#competitions/${row.competition_id}/leaderboard`}>
                              {row.title}
                            </a>
                          </td>
                          <td>
                            #{row.rank} of {row.team_count}
                          </td>
                          <td>
                            <MedalBadge medal={row.medal} />
                          </td>
                          <td>{row.team_name || 'Solo'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted">No final competition results yet.</p>
              )}
            </section>
          )}
          {!publicView && section === 'profile' && profile && (
            <div className="profile-edit-layout">
              <section className="account-card profile-photo">
                <Avatar profile={profile} revision={revision} />
                <h2>Profile photo</h2>
                <label>
                  Upload photo
                  <input
                    type="file"
                    accept="image/png,image/jpeg"
                    disabled={busy}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (!file) return;
                      const form = new FormData();
                      form.set('file', file);
                      void run(async () => {
                        const row = await api<Profile>('/account/avatar', {
                          method: 'PUT',
                          body: form,
                        });
                        setProfile(row);
                        setRevision((n) => n + 1);
                        updated();
                      }, 'Profile photo updated');
                      event.target.value = '';
                    }}
                  />
                </label>
                <small>PNG or JPEG, up to 2 MB. Your photo follows your profile visibility.</small>
                {profile.has_custom_avatar && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await api('/account/avatar', { method: 'DELETE' });
                        setProfile({ ...profile, has_custom_avatar: false });
                        setRevision((n) => n + 1);
                        updated();
                      }, 'Profile photo removed')
                    }
                  >
                    Remove photo
                  </button>
                )}
              </section>
              <form
                className="account-card account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const data = Object.fromEntries(new FormData(event.currentTarget));
                  void run(async () => {
                    setProfile(
                      await api<Profile>('/account/profile', {
                        method: 'PUT',
                        body: JSON.stringify({ ...data, website: data.website || null }),
                      }),
                    );
                    setRevision((n) => n + 1);
                    updated();
                  }, 'Profile saved');
                }}
              >
                <p>@{profile.username}</p>
                <div className="account-fields">
                  {(
                    [
                      ['display_name', 'Display name', 80],
                      ['tagline', 'Tagline', 160],
                      ['pronouns', 'Pronouns', 40],
                      ['occupation', 'Occupation', 100],
                      ['organization', 'Organization', 100],
                      ['location', 'Location', 120],
                    ] as const
                  ).map(([name, label, max]) => (
                    <label key={name}>
                      {label}
                      <input name={name} defaultValue={profile[name]} maxLength={max} />
                    </label>
                  ))}
                </div>
                <label>
                  Website
                  <input name="website" type="url" defaultValue={profile.website || ''} />
                </label>
                <label>
                  About you
                  <textarea name="bio" rows={6} maxLength={5000} defaultValue={profile.bio} />
                </label>
                <div className="form-actions">
                  <button className="button" disabled={busy}>
                    Save profile
                  </button>
                </div>
              </form>
            </div>
          )}
          {!publicView && section === 'settings' && profile && (
            <>
              <form
                className="account-card account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const visibility = String(new FormData(event.currentTarget).get('visibility'));
                  void run(async () => {
                    await api('/account/settings', {
                      method: 'PUT',
                      body: JSON.stringify({ visibility }),
                    });
                    setProfile({ ...profile, visibility: visibility as Profile['visibility'] });
                    updated();
                  }, 'Settings saved');
                }}
              >
                <h2>Profile visibility</h2>
                <p>
                  This controls your profile details and photo. Dataset and notebook visibility is
                  managed on each item.
                </p>
                <label>
                  Who can see your profile?
                  <select name="visibility" defaultValue={profile.visibility}>
                    <option value="public">Everyone</option>
                    <option value="private">Only me</option>
                  </select>
                </label>
                <button className="button" disabled={busy}>
                  Save settings
                </button>
              </form>
              {identities && (
                <section className="account-card linked-identities">
                  <h2>Keycloak sign-in</h2>
                  {linkResult && (
                    <p
                      role={linkResult.error ? 'alert' : 'status'}
                      className={linkResult.error ? 'error' : 'success'}
                    >
                      {linkResult.text}
                    </p>
                  )}
                  {identities.identities.map((identity) => (
                    <article className="account-row" key={identity.id}>
                      <div>
                        <strong>{identity.username || identity.email || 'Keycloak account'}</strong>
                        <p>
                          {[
                            identity.email,
                            `Linked ${new Date(identity.created_at).toLocaleDateString()}`,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                        <small>
                          Last sign-in:{' '}
                          {identity.last_login_at
                            ? new Date(identity.last_login_at).toLocaleString()
                            : 'Never'}
                        </small>
                      </div>
                      {identities.has_password && (
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => {
                            if (
                              window.confirm(
                                'Unlink this Keycloak account? You will sign in with your Arena username and password.',
                              )
                            )
                              void run(async () => {
                                await api(`/account/identities/${identity.id}`, {
                                  method: 'DELETE',
                                });
                                setIdentities(await api<Identities>('/account/identities'));
                              }, 'Keycloak account unlinked');
                          }}
                        >
                          Unlink
                        </button>
                      )}
                    </article>
                  ))}
                  {!identities.identities.length ? (
                    <>
                      <p>
                        Link your Keycloak account to reach this Arena account with “
                        {identities.label}”. You will be asked to sign in to Keycloak.
                      </p>
                      <div className="form-actions">
                        <a
                          className="button secondary"
                          href={oidcLoginPath('account/settings', true)}
                        >
                          Link Keycloak account
                        </a>
                      </div>
                    </>
                  ) : (
                    !identities.has_password && (
                      <p className="auth-notice">
                        This account signs in only through Keycloak, so it cannot be unlinked.
                      </p>
                    )
                  )}
                </section>
              )}
              {user?.has_password === false ? (
                <section className="account-card">
                  <h2>Password</h2>
                  <p>
                    Your password is managed in Keycloak. Change it there; Arena does not keep a
                    password for this account.
                  </p>
                </section>
              ) : (
              <form
                className="account-card account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = event.currentTarget;
                  const data = Object.fromEntries(new FormData(form));
                  void run(async () => {
                    await api('/account/password', { method: 'PUT', body: JSON.stringify(data) });
                    form.reset();
                  }, 'Password changed. Other sessions and API tokens were revoked.');
                }}
              >
                <h2>Change password</h2>
                <p>Changing your password signs out other sessions and revokes all API tokens.</p>
                <label>
                  Current password
                  <input
                    name="current_password"
                    type="password"
                    autoComplete="current-password"
                    required
                    maxLength={128}
                  />
                </label>
                <label>
                  New password
                  <input
                    name="new_password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={10}
                    maxLength={128}
                  />
                </label>
                <button className="button" disabled={busy}>
                  Change password
                </button>
              </form>
              )}
            </>
          )}
          {!publicView && section === 'tokens' && (
            <>
              <p>
                Create expiring credentials for command-line tools. Tokens access only content your
                account is authorized to access. Account settings require a browser session.
              </p>
              <form
                className="account-card account-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = event.currentTarget;
                  const data = Object.fromEntries(new FormData(form));
                  setSecret('');
                  void run(async () => {
                    const result = await api<{ token: string }>('/account/tokens', {
                      method: 'POST',
                      body: JSON.stringify({ ...data, days: Number(data.days) }),
                    });
                    setSecret(result.token);
                    form.reset();
                    await tokenRefresh();
                  }, 'Token created');
                }}
              >
                <label>
                  Token name
                  <input name="name" required maxLength={80} placeholder="Local CLI" />
                </label>
                <div className="account-fields">
                  <label>
                    Permissions
                    <select name="scope">
                      <option value="read">Read only</option>
                      <option value="read-write">Read and write</option>
                    </select>
                  </label>
                  <label>
                    Expires in
                    <select name="days" defaultValue="30">
                      <option value="7">7 days</option>
                      <option value="30">30 days</option>
                      <option value="90">90 days</option>
                      <option value="365">365 days</option>
                    </select>
                  </label>
                </div>
                <button className="button" disabled={busy}>
                  Create API token
                </button>
              </form>
              {secret && (
                <section className="account-card token-secret">
                  <h2>Copy your token now</h2>
                  <p>This value is shown only once. Store it securely.</p>
                  <code>{secret}</code>
                  <div className="form-actions">
                    <button
                      className="button secondary"
                      onClick={() =>
                        void run(async () => navigator.clipboard.writeText(secret), 'Token copied')
                      }
                    >
                      Copy token
                    </button>
                    <button className="text-button" onClick={() => setSecret('')}>
                      Hide token
                    </button>
                  </div>
                </section>
              )}
              <section className="account-card">
                <h2>Your tokens</h2>
                {!tokens.length && <p>No API tokens created.</p>}
                {tokens.map((token) => (
                  <article className="account-row" key={token.id}>
                    <div>
                      <strong>{token.name}</strong>
                      <p>
                        {token.prefix}… · {token.scope} ·{' '}
                        {token.expires_at * 1000 < Date.now() ? 'Expired' : 'Expires'}{' '}
                        {new Date(token.expires_at * 1000).toLocaleDateString()}
                      </p>
                      <small>
                        Last used:{' '}
                        {token.last_used_at
                          ? new Date(token.last_used_at).toLocaleString()
                          : 'Never'}
                      </small>
                    </div>
                    <button
                      className="button secondary"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(`Revoke ${token.name}? Clients using it will lose access.`)
                        )
                          void run(async () => {
                            await api(`/account/tokens/${token.id}`, { method: 'DELETE' });
                            setSecret('');
                            await tokenRefresh();
                          }, 'Token revoked');
                      }}
                    >
                      Revoke
                    </button>
                  </article>
                ))}
              </section>
              <section className="account-card">
                <h2>Use from the command line</h2>
                <p>
                  Set <code>ARENA_TOKEN</code> in your shell, then send it as a bearer token:
                </p>
                <pre>{`curl -H "Authorization: Bearer $ARENA_TOKEN" ${window.location.origin}/api/work`}</pre>
              </section>
            </>
          )}
          {!publicView && section === 'groups' && (
            <>
              <p>
                Organize your groups and manage membership. Competition teams and content-sharing
                permissions are managed separately.
              </p>
              <div className="account-fields">
                <form
                  className="account-card account-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = event.currentTarget;
                    const data = Object.fromEntries(new FormData(form));
                    void run(async () => {
                      await api('/account/groups', { method: 'POST', body: JSON.stringify(data) });
                      form.reset();
                      await groupRefresh();
                    }, 'Group created');
                  }}
                >
                  <h2>Create a group</h2>
                  <label>
                    Group name
                    <input name="name" required minLength={3} maxLength={80} />
                  </label>
                  <label>
                    Description
                    <textarea name="description" maxLength={1000} />
                  </label>
                  <button className="button" disabled={busy}>
                    Create group
                  </button>
                </form>
                <form
                  className="account-card account-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = event.currentTarget;
                    const code = new FormData(form).get('code');
                    void run(async () => {
                      await api('/account/groups/join', {
                        method: 'POST',
                        body: JSON.stringify({ code }),
                      });
                      form.reset();
                      await groupRefresh();
                    }, 'Joined group');
                  }}
                >
                  <h2>Join a group</h2>
                  <label>
                    Invite code
                    <input name="code" required maxLength={80} />
                  </label>
                  <button className="button secondary" disabled={busy}>
                    Join group
                  </button>
                </form>
              </div>
              {!groups.length && <p>You are not in any groups yet.</p>}
              {groups.map((group) => (
                <section className="account-card" key={group.id}>
                  <h2>{group.name}</h2>
                  <p>{group.description}</p>
                  {group.owner_id === user?.id && (
                    <form
                      className="account-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const data = Object.fromEntries(new FormData(event.currentTarget));
                        void run(async () => {
                          await api(`/account/groups/${group.id}`, {
                            method: 'PUT',
                            body: JSON.stringify(data),
                          });
                          await groupRefresh();
                        }, 'Group updated');
                      }}
                    >
                      <label>
                        Group name
                        <input
                          name="name"
                          required
                          minLength={3}
                          maxLength={80}
                          defaultValue={group.name}
                        />
                      </label>
                      <label>
                        Description
                        <textarea
                          name="description"
                          maxLength={1000}
                          defaultValue={group.description}
                        />
                      </label>
                      <button className="button secondary" disabled={busy}>
                        Save group
                      </button>
                    </form>
                  )}
                  {group.invite_code && (
                    <div className="group-invite">
                      <p>
                        Invite code: <code>{group.invite_code}</code>
                      </p>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await api(`/account/groups/${group.id}/invite`, { method: 'POST' });
                            await groupRefresh();
                          }, 'New invite code created; the previous code no longer works')
                        }
                      >
                        Replace invite code
                      </button>
                    </div>
                  )}
                  <h3>Members</h3>
                  {group.members.map((member) => (
                    <div className="account-row" key={member.id}>
                      <span>
                        {member.username}
                        {member.id === group.owner_id ? ' · Owner' : ''}
                      </span>
                      {group.owner_id === user?.id && member.id !== user.id && (
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm(`Remove ${member.username} from this group?`))
                              void run(async () => {
                                await api(`/account/groups/${group.id}/members/${member.id}`, {
                                  method: 'DELETE',
                                });
                                await groupRefresh();
                              }, 'Member removed');
                          }}
                        >
                          Remove member
                        </button>
                      )}
                    </div>
                  ))}
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          group.owner_id === user?.id
                            ? `Delete ${group.name} and its memberships?`
                            : `Leave ${group.name}?`,
                        )
                      )
                        void run(
                          async () => {
                            await api(
                              group.owner_id === user?.id
                                ? `/account/groups/${group.id}`
                                : `/account/groups/${group.id}/members/${user?.id}`,
                              { method: 'DELETE' },
                            );
                            await groupRefresh();
                          },
                          group.owner_id === user?.id ? 'Group deleted' : 'Left group',
                        );
                    }}
                  >
                    {group.owner_id === user?.id ? 'Delete group' : 'Leave group'}
                  </button>
                </section>
              ))}
            </>
          )}
        </>
      )}
    </section>
  );
}
