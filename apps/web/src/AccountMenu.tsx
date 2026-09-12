import { useEffect, useRef, useState } from 'react';
import { Bell, FolderOpen, KeyRound, LogOut, Settings, UserRound, Users, X } from 'lucide-react';
import { api, type User } from './api';
import ProfilePhoto from './ProfilePhoto';

export type Profile = {
  username: string;
  display_name: string;
  tagline: string;
  pronouns: string;
  occupation: string;
  organization: string;
  location: string;
  bio: string;
  website: string | null;
  avatar_url: string | null;
  has_custom_avatar: boolean;
  joined_at: string;
  visibility: 'public' | 'private';
};
export function Avatar({ profile, revision = 0 }: { profile?: Profile | null; revision?: number }) {
  return (
    <span className="account-avatar">
      <ProfilePhoto
        src={profile?.avatar_url ? `${profile.avatar_url}?v=${revision}` : null}
        alt={profile ? `${profile.username}'s profile photo` : 'Default profile photo'}
      />
    </span>
  );
}

type Notice = { id: number; title: string; body: string; created_at: string; read: boolean };
export default function AccountMenu({
  user,
  revision,
  navigate,
  logout,
}: {
  user: User;
  revision: number;
  navigate: (path: string) => void;
  logout: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    api<Profile>('/account/profile')
      .then((row) => {
        if (active) setProfile(row);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [user.id, revision]);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    let active = true;
    setLoading(true);
    setError('');
    api<Notice[]>('/account/notifications')
      .then((rows) => {
        if (active) setNotices(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      document.body.style.overflow = previous;
    };
  }, [open]);
  function close() {
    dialog.current?.close();
    setOpen(false);
    trigger.current?.focus();
  }
  const links = [
    ['work', 'Your work', FolderOpen],
    ['account/profile', 'Your profile', UserRound],
    ['account/groups', 'Your groups', Users],
    ['account/tokens', 'Your API tokens', KeyRound],
    ['account/settings', 'Settings', Settings],
  ] as const;
  return (
    <>
      <button
        ref={trigger}
        className="account-avatar-button"
        aria-label="Open user menu"
        title="Your account"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <Avatar profile={profile} revision={revision} />
      </button>
      <dialog
        ref={dialog}
        className="account-drawer"
        aria-label="Your account"
        onClose={() => setOpen(false)}
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const box = event.currentTarget.getBoundingClientRect();
          if (event.clientX < box.left || event.clientX > box.right) close();
        }}
      >
        <header>
          <Avatar profile={profile} revision={revision} />
          <strong>{profile?.display_name || user.username}</strong>
          <button className="icon-button" aria-label="Close user menu" onClick={close}>
            <X />
          </button>
        </header>
        <nav aria-label="User management">
          {links.map(([path, label, Icon]) => (
            <button
              key={path}
              onClick={() => {
                close();
                navigate(path);
              }}
            >
              <Icon size={22} />
              {label}
            </button>
          ))}
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError('');
              try {
                await api('/auth/logout', { method: 'POST' });
                close();
                logout();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <LogOut size={22} />
            {busy ? 'Signing out…' : 'Log out'}
          </button>
        </nav>
        <section className="account-notifications">
          <h2>
            <Bell size={22} />
            Your notifications <small>{notices.filter((n) => !n.read).length} unread</small>
          </h2>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {loading ? (
            <p role="status">Loading notifications…</p>
          ) : (
            !notices.length && <p>No service notifications yet.</p>
          )}
          {notices.map((notice) => (
            <article key={notice.id} className={notice.read ? 'read' : 'unread'}>
              <small>Arena service team · {new Date(notice.created_at).toLocaleDateString()}</small>
              <h3>{notice.title}</h3>
              <p>{notice.body}</p>
              {!notice.read && (
                <button
                  className="text-button"
                  onClick={async () => {
                    try {
                      await api(`/account/notifications/${notice.id}/read`, { method: 'POST' });
                      setNotices((rows) =>
                        rows.map((row) => (row.id === notice.id ? { ...row, read: true } : row)),
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  Mark as read
                </button>
              )}
            </article>
          ))}
        </section>
      </dialog>
    </>
  );
}
