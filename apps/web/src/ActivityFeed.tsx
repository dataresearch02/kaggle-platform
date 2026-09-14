import { useEffect, useState } from 'react';
import { Code2, Database, Layers3, MessageSquare, Trophy } from 'lucide-react';
import { apiPage } from './api';
import type { ActivityItem } from './Community';

const icons = {
  notebook: Code2,
  dataset: Database,
  model: Layers3,
  topic: MessageSquare,
  medal: Trophy,
};
const PAGE_SIZE = 20;

/** Paginated public activity: the home feed or a profile's Activity tab. */
export default function ActivityFeed({ path, empty }: { path: string; empty: string }) {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const separator = path.includes('?') ? '&' : '?';
  useEffect(() => {
    let active = true;
    setItems([]);
    setLoading(true);
    setError('');
    apiPage<ActivityItem>(`${path}${separator}limit=${PAGE_SIZE}`)
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
  }, [path]);
  return (
    <div className="activity-feed">
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <ul>
        {items.map((item) => {
          const Icon = icons[item.kind];
          return (
            <li key={`${item.kind}-${item.id}`}>
              <span className={`activity-icon ${item.kind}`}>
                <Icon size={16} aria-hidden="true" />
              </span>
              <div>
                <p>
                  <a href={`#profile/${encodeURIComponent(item.actor)}`}>{item.actor}</a>{' '}
                  {item.message}{' '}
                  {item.url ? <a href={item.url}>{item.title}</a> : <strong>{item.title}</strong>}
                  {item.kind === 'medal' && item.detail.rank && (
                    <span className="muted">
                      {' '}
                      (#{item.detail.rank} of {item.detail.team_count})
                    </span>
                  )}
                </p>
                <small className="muted">{new Date(item.created_at).toLocaleString()}</small>
              </div>
            </li>
          );
        })}
      </ul>
      {loading && <p role="status">Loading activity…</p>}
      {!loading && !items.length && !error && <p className="muted">{empty}</p>}
      {!loading && items.length < total && (
        <button
          className="button secondary"
          onClick={async () => {
            setLoading(true);
            try {
              const page = await apiPage<ActivityItem>(
                `${path}${separator}offset=${items.length}&limit=${PAGE_SIZE}`,
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
          Load more activity
        </button>
      )}
    </div>
  );
}
