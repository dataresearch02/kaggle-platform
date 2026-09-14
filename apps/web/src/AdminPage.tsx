import { useEffect, useState } from 'react';
import { ArrowUpRight, Search } from 'lucide-react';
import { api, apiPage, type Site, type User } from './api';
import Markdown from './Markdown';
import {
  ReasonDialog,
  moderate,
  moderationDialog,
  reportKindLabels,
  type ReportKind,
} from './Moderation';

export const adminTabs = ['users', 'reports', 'hidden', 'audit', 'settings'] as const;
export type AdminTab = (typeof adminTabs)[number];
const tabLabels: Record<AdminTab, string> = {
  users: 'Users',
  reports: 'Reports',
  hidden: 'Hidden content',
  audit: 'Audit log',
  settings: 'Settings',
};

type PublicSettings = Pick<Site, 'registration_open' | 'local_login_enabled' | 'announcement'>;
export function adminRouteFromHash(): AdminTab | null {
  const match = window.location.hash.match(/^#admin(?:\/([a-z]+))?$/);
  if (!match) return null;
  return adminTabs.includes(match[1] as AdminTab) ? (match[1] as AdminTab) : 'users';
}

type Role = 'user' | 'host' | 'admin';
type AdminUser = {
  id: number;
  username: string;
  role: Role;
  status: 'active' | 'suspended';
  created_at: string;
  active_sessions: number;
  api_tokens: number;
};
type Target = {
  available: boolean;
  title: string;
  owner: string | null;
  hidden: boolean;
  hidden_reason: string;
  link: string | null;
};
type Report = {
  id: number;
  kind: ReportKind;
  target_id: number;
  reason: string;
  status: 'open' | 'resolved';
  reporter: string;
  created_at: string;
  resolution_note: string;
  resolved_by: string | null;
  resolved_at: string | null;
  target: Target;
};
type HiddenItem = Target & { kind: ReportKind; id: number };
type AuditEntry = {
  id: number;
  actor: string;
  action: string;
  target_kind: string;
  target_id: string;
  detail: Record<string, unknown>;
  created_at: string;
};
type Settings = Site & { competition_creation: 'hosts' | 'everyone' };

const PAGE_SIZE = 25;
const date = (value: string | null) => (value ? new Date(value).toLocaleString() : '');

function useDebounced<T>(value: T, delay = 250) {
  const [current, setCurrent] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setCurrent(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return current;
}

function usePaged<T>(path: string) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const url = (offset: number) =>
    `${path}${path.includes('?') ? '&' : '?'}offset=${offset}&limit=${PAGE_SIZE}`;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    apiPage<T>(url(0))
      .then((page) => {
        if (active) {
          setItems(page.items);
          setTotal(page.total);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [path, revision]);
  async function more() {
    setLoading(true);
    setError('');
    try {
      const page = await apiPage<T>(url(items.length));
      setItems((old) => [...old, ...page.items]);
      setTotal(page.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return {
    items,
    setItems,
    total,
    loading,
    error,
    setError,
    more,
    reload: () => setRevision((value) => value + 1),
  };
}

function ListFooter({
  shown,
  total,
  loading,
  more,
  noun,
}: {
  shown: number;
  total: number;
  loading: boolean;
  more: () => void;
  noun: string;
}) {
  return (
    <div className="admin-list-footer">
      {loading ? (
        <p role="status">Loading {noun}…</p>
      ) : (
        <span className="muted">
          {total ? `Showing ${shown} of ${total} ${noun}` : `No ${noun} found`}
        </span>
      )}
      {!loading && shown < total && (
        <button className="button secondary" onClick={more}>
          Load more
        </button>
      )}
    </div>
  );
}

export default function AdminPage({
  tab,
  user,
  siteChanged,
}: {
  tab: AdminTab;
  user: User | null;
  siteChanged: (site: PublicSettings) => void;
}) {
  if (user?.role !== 'admin')
    return (
      <section className="account-page">
        <h1>Administration</h1>
        <p>Administrator access is required to view this page.</p>
      </section>
    );
  return (
    <section className="admin-page">
      <header className="account-page-heading">
        <div>
          <span className="eyebrow">OPERATIONS</span>
          <h1>Administration</h1>
        </div>
      </header>
      <nav className="competition-tabs admin-tabs" aria-label="Administration sections">
        {adminTabs.map((name) => (
          <a
            key={name}
            href={`#admin/${name}`}
            aria-current={tab === name ? 'page' : undefined}
          >
            {tabLabels[name]}
          </a>
        ))}
      </nav>
      <div className="admin-panel">
        {tab === 'users' && <UsersTab user={user} />}
        {tab === 'reports' && <ReportsTab />}
        {tab === 'hidden' && <HiddenTab />}
        {tab === 'audit' && <AuditTab />}
        {tab === 'settings' && <SettingsTab siteChanged={siteChanged} />}
      </div>
    </section>
  );
}

type UserAction = 'suspend' | 'reset' | 'revoke';
const userDialogs: Record<UserAction, { title: string; description: string; confirm: string }> = {
  suspend: {
    title: 'Suspend account',
    description:
      'The user cannot sign in or use existing sessions and API tokens until reactivated. Their content stays in place.',
    confirm: 'Suspend',
  },
  reset: {
    title: 'Reset password',
    description:
      'A temporary password is generated and shown once. All of the user’s sessions and API tokens are revoked.',
    confirm: 'Reset password',
  },
  revoke: {
    title: 'Revoke sessions',
    description: 'The user is signed out everywhere. API tokens keep working.',
    confirm: 'Revoke sessions',
  },
};

function UsersTab({ user }: { user: User }) {
  const [query, setQuery] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState('');
  const q = useDebounced(query);
  const params = new URLSearchParams({ q });
  if (role) params.set('role', role);
  if (status) params.set('status', status);
  const list = usePaged<AdminUser>(`/admin/users?${params}`);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [secret, setSecret] = useState<{ username: string; password: string } | null>(null);
  const [pending, setPending] = useState<{ action: UserAction; row: AdminUser } | null>(null);
  const [dialogError, setDialogError] = useState('');
  function replace(row: AdminUser) {
    list.setItems((items) => items.map((item) => (item.id === row.id ? row : item)));
  }
  async function update(row: AdminUser, change: Partial<Pick<AdminUser, 'role' | 'status'>>) {
    setBusy(true);
    list.setError('');
    setNotice('');
    try {
      replace(
        await api<AdminUser>(`/admin/users/${row.id}`, {
          method: 'PUT',
          body: JSON.stringify(change),
        }),
      );
      setNotice(`Updated ${row.username}`);
    } catch (e) {
      list.setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!pending) return;
    const { action, row } = pending;
    setBusy(true);
    setDialogError('');
    setNotice('');
    try {
      if (action === 'suspend') await update(row, { status: 'suspended' });
      else if (action === 'reset') {
        const result = await api<{ temporary_password: string }>(
          `/admin/users/${row.id}/password-reset`,
          { method: 'POST' },
        );
        setSecret({ username: row.username, password: result.temporary_password });
        list.reload();
      } else {
        const result = await api<{ sessions_revoked: number }>(
          `/admin/users/${row.id}/revoke-sessions`,
          { method: 'POST' },
        );
        setNotice(`Revoked ${result.sessions_revoked} sessions for ${row.username}`);
        list.reload();
      }
      setPending(null);
    } catch (e) {
      setDialogError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="admin-filters">
        <label className="search">
          <Search size={18} />
          <input
            aria-label="Search usernames"
            placeholder="Search usernames…"
            maxLength={40}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          Role
          <select value={role} onChange={(event) => setRole(event.target.value)}>
            <option value="">All roles</option>
            <option value="user">User</option>
            <option value="host">Host</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
        </label>
      </div>
      {list.error && (
        <p className="error" role="alert">
          {list.error}
        </p>
      )}
      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
      {secret && (
        <div className="admin-secret" role="status">
          <strong>Temporary password for {secret.username}</strong>
          <code>{secret.password}</code>
          <p>
            It is shown only once. Share it through a secure channel and ask the user to change it
            from Account settings.
          </p>
          <button className="text-button" onClick={() => setSecret(null)}>
            I have saved it
          </button>
        </div>
      )}
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Status</th>
              <th>Sessions · tokens</th>
              <th>Joined</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {list.items.map((row) => {
              const self = row.id === user.id;
              return (
                <tr key={row.id}>
                  <td>
                    <a href={`#profile/${row.username}`}>{row.username}</a>
                    {self && <small className="muted"> (you)</small>}
                  </td>
                  <td>
                    <select
                      aria-label={`Role for ${row.username}`}
                      value={row.role}
                      disabled={busy || self}
                      onChange={(event) => void update(row, { role: event.target.value as Role })}
                    >
                      <option value="user">User</option>
                      <option value="host">Host</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td>
                    <span className={`admin-badge ${row.status}`}>{row.status}</span>
                  </td>
                  <td>
                    {row.active_sessions} · {row.api_tokens}
                  </td>
                  <td>{new Date(row.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="admin-row-actions">
                      {row.status === 'suspended' ? (
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() => void update(row, { status: 'active' })}
                        >
                          Activate
                        </button>
                      ) : (
                        <button
                          className="text-button"
                          disabled={busy || self}
                          onClick={() => setPending({ action: 'suspend', row })}
                        >
                          Suspend
                        </button>
                      )}
                      <button
                        className="text-button"
                        disabled={busy || self}
                        onClick={() => setPending({ action: 'reset', row })}
                      >
                        Reset password
                      </button>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => setPending({ action: 'revoke', row })}
                      >
                        Revoke sessions
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ListFooter
        shown={list.items.length}
        total={list.total}
        loading={list.loading}
        more={() => void list.more()}
        noun="users"
      />
      {pending && (
        <ReasonDialog
          title={`${userDialogs[pending.action].title}: ${pending.row.username}`}
          description={userDialogs[pending.action].description}
          confirm={userDialogs[pending.action].confirm}
          danger={pending.action !== 'revoke'}
          busy={busy}
          error={dialogError}
          close={() => {
            setPending(null);
            setDialogError('');
          }}
          submit={() => void confirm()}
        />
      )}
    </>
  );
}

type ContentAction = 'hide' | 'unhide' | 'delete' | 'resolve';

function ContentDialog({
  action,
  kind,
  id,
  reportId,
  close,
  done,
}: {
  action: ContentAction;
  kind: ReportKind;
  id: number;
  reportId?: number;
  close: () => void;
  done: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const label = reportKindLabels[kind].toLowerCase();
  const config =
    action === 'resolve'
      ? {
          title: 'Resolve report',
          description: 'Resolving closes the report. Hide or delete the item separately if needed.',
          label: 'Resolution note (optional)',
          confirm: 'Resolve',
        }
      : moderationDialog(action, label, kind);
  return (
    <ReasonDialog
      {...config}
      busy={busy}
      error={error}
      close={close}
      submit={async (reason) => {
        setBusy(true);
        setError('');
        try {
          if (action === 'resolve')
            await api(`/admin/reports/${reportId}/resolve`, {
              method: 'POST',
              body: JSON.stringify({ note: reason }),
            });
          else await moderate(kind, id, action, reason);
          done();
        } catch (e) {
          setError((e as Error).message);
          setBusy(false);
        }
      }}
    />
  );
}

function TargetLink({ target }: { target: Target }) {
  return target.link ? (
    <a className="text-button" href={target.link}>
      Open item <ArrowUpRight size={14} />
    </a>
  ) : null;
}

function ReportsTab() {
  const [status, setStatus] = useState('open');
  const list = usePaged<Report>(`/admin/reports?status=${status}`);
  const [pending, setPending] = useState<{ action: ContentAction; report: Report } | null>(null);
  return (
    <>
      <div className="admin-filters">
        <label>
          Reports
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
            <option value="all">All</option>
          </select>
        </label>
      </div>
      {list.error && (
        <p className="error" role="alert">
          {list.error}
        </p>
      )}
      <div className="admin-cards">
        {list.items.map((report) => (
          <article className="admin-card" key={report.id}>
            <header>
              <span className="admin-badge">{reportKindLabels[report.kind] || report.kind}</span>
              <span className={`admin-badge ${report.status}`}>{report.status}</span>
              {report.target.hidden && <span className="admin-badge suspended">hidden</span>}
            </header>
            <h3>{report.target.title}</h3>
            <p className="muted">
              {report.target.owner ? `By ${report.target.owner} · ` : ''}Reported by{' '}
              {report.reporter} · {date(report.created_at)}
            </p>
            <p className="admin-reason">{report.reason}</p>
            {report.status === 'resolved' && (
              <p className="muted">
                Resolved by {report.resolved_by || 'an administrator'} · {date(report.resolved_at)}
                {report.resolution_note ? ` · ${report.resolution_note}` : ''}
              </p>
            )}
            <div className="admin-row-actions">
              <TargetLink target={report.target} />
              {report.target.available && (
                <>
                  <button
                    className="text-button"
                    onClick={() =>
                      setPending({ action: report.target.hidden ? 'unhide' : 'hide', report })
                    }
                  >
                    {report.target.hidden ? 'Unhide' : 'Hide'}
                  </button>
                  <button
                    className="text-button danger-text"
                    onClick={() => setPending({ action: 'delete', report })}
                  >
                    Delete
                  </button>
                </>
              )}
              {report.status === 'open' && (
                <button
                  className="button secondary small"
                  onClick={() => setPending({ action: 'resolve', report })}
                >
                  Resolve
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
      <ListFooter
        shown={list.items.length}
        total={list.total}
        loading={list.loading}
        more={() => void list.more()}
        noun="reports"
      />
      {pending && (
        <ContentDialog
          action={pending.action}
          kind={pending.report.kind}
          id={pending.report.target_id}
          reportId={pending.report.id}
          close={() => setPending(null)}
          done={() => {
            setPending(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function HiddenTab() {
  const [kind, setKind] = useState('');
  const list = usePaged<HiddenItem>(`/admin/hidden${kind ? `?kind=${kind}` : ''}`);
  const [pending, setPending] = useState<{ action: ContentAction; item: HiddenItem } | null>(
    null,
  );
  return (
    <>
      <div className="admin-filters">
        <label>
          Content type
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="">All types</option>
            {Object.entries(reportKindLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {list.error && (
        <p className="error" role="alert">
          {list.error}
        </p>
      )}
      <div className="admin-cards">
        {list.items.map((item) => (
          <article className="admin-card" key={`${item.kind}-${item.id}`}>
            <header>
              <span className="admin-badge">{reportKindLabels[item.kind]}</span>
            </header>
            <h3>{item.title}</h3>
            <p className="muted">
              {item.owner ? `By ${item.owner} · ` : ''}Reason: {item.hidden_reason || '—'}
            </p>
            <div className="admin-row-actions">
              <TargetLink target={item} />
              <button
                className="text-button"
                onClick={() => setPending({ action: 'unhide', item })}
              >
                Unhide
              </button>
              <button
                className="text-button danger-text"
                onClick={() => setPending({ action: 'delete', item })}
              >
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
      <ListFooter
        shown={list.items.length}
        total={list.total}
        loading={list.loading}
        more={() => void list.more()}
        noun="hidden items"
      />
      {pending && (
        <ContentDialog
          action={pending.action}
          kind={pending.item.kind}
          id={pending.item.id}
          close={() => setPending(null)}
          done={() => {
            setPending(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function AuditTab() {
  const [actorInput, setActorInput] = useState('');
  const [actionInput, setActionInput] = useState('');
  const actor = useDebounced(actorInput);
  const action = useDebounced(actionInput);
  const list = usePaged<AuditEntry>(`/admin/audit?${new URLSearchParams({ actor, action })}`);
  return (
    <>
      <div className="admin-filters">
        <label>
          Actor
          <input
            placeholder="Username or system"
            maxLength={40}
            value={actorInput}
            onChange={(event) => setActorInput(event.target.value)}
          />
        </label>
        <label>
          Action
          <input
            placeholder="e.g. user. or content.hide"
            maxLength={60}
            value={actionInput}
            onChange={(event) => setActionInput(event.target.value)}
          />
        </label>
      </div>
      {list.error && (
        <p className="error" role="alert">
          {list.error}
        </p>
      )}
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Target</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {list.items.map((row) => (
              <tr key={row.id}>
                <td>{date(row.created_at)}</td>
                <td>{row.actor}</td>
                <td>
                  <code>{row.action}</code>
                </td>
                <td>
                  {row.target_kind}
                  {row.target_id ? ` #${row.target_id}` : ''}
                </td>
                <td>
                  <code className="admin-detail">{JSON.stringify(row.detail)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ListFooter
        shown={list.items.length}
        total={list.total}
        loading={list.loading}
        more={() => void list.more()}
        noun="entries"
      />
    </>
  );
}

function SettingsTab({ siteChanged }: { siteChanged: (site: PublicSettings) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api<Settings>('/admin/settings')
      .then((row) => {
        if (active) setSettings(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  if (!settings) return <p role={error ? 'alert' : 'status'}>{error || 'Loading settings…'}</p>;
  const change = (values: Partial<Settings>) => setSettings({ ...settings, ...values });
  return (
    <form
      className="admin-settings"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError('');
        setNotice('');
        try {
          const saved = await api<Settings>('/admin/settings', {
            method: 'PUT',
            body: JSON.stringify(settings),
          });
          setSettings(saved);
          siteChanged({
            registration_open: saved.registration_open,
            local_login_enabled: saved.local_login_enabled,
            announcement: saved.announcement,
          });
          setNotice('Settings saved');
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <fieldset>
        <legend>Accounts</legend>
        <label className="admin-check">
          <input
            type="checkbox"
            checked={settings.registration_open}
            onChange={(event) => change({ registration_open: event.target.checked })}
          />
          <span>
            Registration open
            <small>When closed, new accounts cannot be created.</small>
          </span>
        </label>
        <label className="admin-check">
          <input
            type="checkbox"
            checked={settings.local_login_enabled}
            onChange={(event) => change({ local_login_enabled: event.target.checked })}
          />
          <span>
            Local username and password sign-in
            <small>Administrators can always sign in locally as a break-glass path.</small>
          </span>
        </label>
      </fieldset>
      <fieldset>
        <legend>Content</legend>
        <label>
          Who can create competitions and CSV benchmarks
          <select
            value={settings.competition_creation}
            onChange={(event) =>
              change({ competition_creation: event.target.value as Settings['competition_creation'] })
            }
          >
            <option value="hosts">Hosts and administrators</option>
            <option value="everyone">Every signed-in member</option>
          </select>
        </label>
      </fieldset>
      <fieldset>
        <legend>Announcement</legend>
        <label>
          Markdown shown to every visitor (leave empty for none)
          <textarea
            rows={4}
            maxLength={5000}
            value={settings.announcement}
            onChange={(event) => change({ announcement: event.target.value })}
          />
        </label>
        {settings.announcement.trim() && (
          <div className="site-announcement preview" aria-label="Announcement preview">
            <Markdown>{settings.announcement}</Markdown>
          </div>
        )}
      </fieldset>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
      <button className="button" disabled={busy}>
        {busy ? 'Saving…' : 'Save settings'}
      </button>
    </form>
  );
}
