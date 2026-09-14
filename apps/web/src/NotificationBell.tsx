import { useEffect, useRef, useState } from 'react';
import { Bell, Settings, X } from 'lucide-react';
import { api, apiPage, type User } from './api';

type Notice = {
  id: number;
  source: 'activity' | 'service';
  kind: string;
  actor: string | null;
  title: string | null;
  message: string;
  url: string | null;
  available: boolean;
  count: number;
  read: boolean;
  created_at: string;
};
const PAGE_SIZE = 20;
const POLL_MS = 60000;

/** Header bell: unread count, a paginated list, and mark-read controls. */
export default function NotificationBell({ user }: { user: User }) {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notice[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let active = true;
    const refresh = () =>
      api<{ count: number }>('/notifications/unread-count')
        .then((result) => {
          if (active) setCount(result.count);
        })
        .catch(() => {});
    void refresh();
    const timer = setInterval(refresh, POLL_MS);
    window.addEventListener('hashchange', refresh);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener('hashchange', refresh);
    };
  }, [user.id]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError('');
    apiPage<Notice>(`/notifications?limit=${PAGE_SIZE}`)
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
    const outside = (event: MouseEvent) => {
      if (
        !panel.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      active = false;
      document.removeEventListener('mousedown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);
  async function markRead(notice: Notice) {
    if (notice.read) return;
    const result = await api<{ count: number }>(
      `/notifications/${notice.source}/${notice.id}/read`,
      { method: 'POST' },
    );
    setCount(result.count);
    setItems((rows) =>
      rows.map((row) =>
        row.id === notice.id && row.source === notice.source ? { ...row, read: true } : row,
      ),
    );
  }
  return (
    <div className="notification-bell">
      <button
        ref={trigger}
        className="icon-button notification-trigger"
        aria-label={count ? `Notifications, ${count} unread` : 'Notifications'}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen(!open)}
      >
        <Bell size={20} />
        {count > 0 && <span className="notification-count">{count > 99 ? '99+' : count}</span>}
      </button>
      {open && (
        <div ref={panel} className="notification-panel" role="dialog" aria-label="Notifications">
          <header>
            <h2>Notifications</h2>
            <button
              className="text-button"
              disabled={!count}
              onClick={async () => {
                try {
                  await api('/notifications/read-all', { method: 'POST' });
                  setCount(0);
                  setItems((rows) => rows.map((row) => ({ ...row, read: true })));
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Mark all as read
            </button>
            <button
              className="icon-button"
              aria-label="Close notifications"
              onClick={() => setOpen(false)}
            >
              <X size={18} />
            </button>
          </header>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <ul>
            {items.map((notice) => (
              <li
                key={`${notice.source}-${notice.id}`}
                className={notice.read ? 'read' : 'unread'}
              >
                <div>
                  <small>
                    {notice.source === 'service' ? 'Arena service team' : notice.kind} ·{' '}
                    {new Date(notice.created_at).toLocaleString()}
                  </small>
                  {notice.source === 'service' ? (
                    <>
                      <strong>{notice.title}</strong>
                      <p>{notice.message}</p>
                    </>
                  ) : notice.url ? (
                    <a
                      href={notice.url}
                      onClick={() => {
                        void markRead(notice).catch(() => {});
                        setOpen(false);
                      }}
                    >
                      {notice.message}
                    </a>
                  ) : (
                    <p>
                      {notice.message}
                      {!notice.available && (
                        <span className="muted"> · This content is no longer available.</span>
                      )}
                    </p>
                  )}
                </div>
                {!notice.read && (
                  <button
                    className="text-button"
                    aria-label="Mark as read"
                    onClick={() => void markRead(notice).catch((e) => setError(e.message))}
                  >
                    Mark read
                  </button>
                )}
              </li>
            ))}
          </ul>
          {loading && <p role="status">Loading notifications…</p>}
          {!loading && !items.length && !error && <p className="muted">No notifications yet.</p>}
          <footer>
            {items.length < total && !loading && (
              <button
                className="button secondary small"
                onClick={async () => {
                  setLoading(true);
                  try {
                    const page = await apiPage<Notice>(
                      `/notifications?offset=${items.length}&limit=${PAGE_SIZE}`,
                    );
                    setItems((rows) => [...rows, ...page.items]);
                    setTotal(page.total);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Load more
              </button>
            )}
            <a
              className="text-button"
              href="#account/settings"
              onClick={() => setOpen(false)}
            >
              <Settings size={14} /> Notification settings
            </a>
          </footer>
        </div>
      )}
    </div>
  );
}
