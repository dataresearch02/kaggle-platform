import { useEffect, useState } from 'react';
import {
  ArrowUp,
  Bookmark,
  MessageSquare,
  Pin,
  Plus,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import { api, type User } from './api';
import DiscussionCreate from './DiscussionCreate';
import DiscussionAvatar from './DiscussionAvatar';
export type Topic = {
  id: number;
  competition_id: number;
  owner_id: number;
  title: string;
  owner: string;
  created_at: string;
  last_activity: string;
  comment_count: number;
  votes: number;
  pinned: boolean;
  bookmarked: boolean;
  voted: boolean;
};
export default function DiscussionList({
  competitionId,
  user,
  signIn,
  initialQuery = '',
}: {
  competitionId?: number;
  user: User | null;
  signIn: () => void;
  initialQuery?: string;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('recent');
  const [unanswered, setUnanswered] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [items, setItems] = useState<Topic[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [canPin, setCanPin] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    setQuery(initialQuery);
    setOffset(0);
  }, [initialQuery]);
  useEffect(() => {
    let active = true;
    setBusy(true);
    setError('');
    if (!offset) setItems([]);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({
        q: query,
        filter,
        sort,
        unanswered: String(unanswered),
        offset: String(offset),
      });
      if (competitionId) params.set('competition_id', String(competitionId));
      api<{ items: Topic[]; next_offset: number | null; can_pin: boolean }>(
        `/competition-discussions?${params}`,
      )
        .then((data) => {
          if (active) {
            setItems((old) =>
              offset
                ? [...old, ...data.items.filter((row) => !old.some((item) => item.id === row.id))]
                : data.items,
            );
            setNext(data.next_offset);
            setCanPin(data.can_pin);
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setBusy(false);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [competitionId, query, filter, sort, unanswered, offset, revision, user?.id]);
  async function action(row: Topic, kind: 'bookmark' | 'pin' | 'vote') {
    if (!user) {
      signIn();
      return;
    }
    setMutating(true);
    setError('');
    try {
      if (kind === 'vote')
        await api(`/engagement/competition-post/${row.id}/reactions/like`, {
          method: row.voted ? 'DELETE' : 'PUT',
        });
      else
        await api(`/competition-discussions/${row.id}/${kind}`, {
          method: 'PUT',
          body: JSON.stringify({ enabled: kind === 'pin' ? !row.pinned : !row.bookmarked }),
        });
      setOffset(0);
      setRevision((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setMutating(false);
    }
  }
  return (
    <section className="discussion-list" aria-label="Discussion topics">
      <header className="discussion-list-heading">
        <h2>{competitionId ? 'Discussion' : 'Discussions'}</h2>
        {competitionId && (
          <button
            className="button secondary"
            onClick={() => (user ? setCreating(true) : signIn())}
          >
            <Plus size={18} /> New discussion
          </button>
        )}
      </header>
      <div className="discussion-search">
        <Search size={21} />
        <input
          aria-label="Search discussions"
          placeholder="Search discussions"
          maxLength={160}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
        <button aria-expanded={filtersOpen} onClick={() => setFiltersOpen(!filtersOpen)}>
          <SlidersHorizontal size={18} /> Filters
        </button>
      </div>
      {filtersOpen && (
        <div className="discussion-filters">
          <label>
            <input
              type="checkbox"
              checked={unanswered}
              onChange={(e) => {
                setUnanswered(e.target.checked);
                setOffset(0);
              }}
            />{' '}
            Without comments
          </label>
        </div>
      )}
      <div className="discussion-list-controls">
        <div role="group" aria-label="Filter discussions">
          {['all', 'owned', 'bookmarks'].map((value) => (
            <button
              key={value}
              aria-pressed={filter === value}
              onClick={() => {
                if (value !== 'all' && !user) {
                  signIn();
                  return;
                }
                setFilter(value);
                setOffset(0);
              }}
            >
              {value === 'all' ? 'All' : value === 'owned' ? 'Owned' : 'Bookmarks'}
            </button>
          ))}
        </div>
        <select
          aria-label="Sort discussions"
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
            setOffset(0);
          }}
        >
          <option value="recent">Recent Comments</option>
          <option value="newest">Newest Topics</option>
          <option value="votes">Most Votes</option>
          <option value="comments">Most Comments</option>
        </select>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {[true, false].map((pinned) => {
        const rows = items.filter((row) => row.pinned === pinned);
        if (!rows.length) return null;
        return (
          <section key={String(pinned)} aria-label={pinned ? 'Pinned topics' : 'All other topics'}>
            <h3 className="discussion-group-label">
              {pinned ? 'Pinned topics' : 'All other topics'}
            </h3>
            {rows.map((row) => (
              <article className="discussion-topic-row" key={row.id}>
                <DiscussionAvatar username={row.owner} pinned={row.pinned} />
                <div className="discussion-topic-copy">
                  <a href={`#competitions/${row.competition_id}/discussion/${row.id}`}>
                    <h3>{row.title}</h3>
                  </a>
                  <p>
                    {row.owner} · {row.comment_count ? 'Last comment' : 'Posted'}{' '}
                    {new Date(row.last_activity).toLocaleDateString()}
                  </p>
                </div>
                <div className="discussion-topic-actions">
                  <button
                    className="discussion-votes"
                    aria-label={`Upvote ${row.title}`}
                    aria-pressed={row.voted}
                    disabled={mutating}
                    onClick={() => void action(row, 'vote')}
                  >
                    <ArrowUp size={14} />
                    {row.votes}
                  </button>
                  <span>
                    <MessageSquare size={14} /> {row.comment_count} comments
                  </span>
                  <div>
                    <button
                      aria-label={`Bookmark ${row.title}`}
                      aria-pressed={row.bookmarked}
                      disabled={mutating}
                      onClick={() => void action(row, 'bookmark')}
                    >
                      <Bookmark size={16} />
                    </button>
                    {canPin && (
                      <button
                        aria-label={`${row.pinned ? 'Unpin' : 'Pin'} ${row.title}`}
                        disabled={mutating}
                        onClick={() => void action(row, 'pin')}
                      >
                        <Pin size={16} />
                      </button>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </section>
        );
      })}
      {busy && <p role="status">Loading discussions…</p>}
      {!busy && !error && !items.length && (
        <div className="empty">
          <h3>No discussions found</h3>
          <p>Try another search or filter.</p>
        </div>
      )}
      {next !== null && !busy && (
        <button className="button secondary" onClick={() => setOffset(next)}>
          Load more topics
        </button>
      )}
      {creating && competitionId && (
        <DiscussionCreate competitionId={competitionId} close={() => setCreating(false)} />
      )}
    </section>
  );
}
