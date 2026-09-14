import { useEffect, useState } from 'react';
import {
  Bookmark,
  Lock,
  MessageSquare,
  Pin,
  Plus,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import { api, type User } from './api';
import DiscussionCreate, { type DiscussionScope } from './DiscussionCreate';
import DiscussionAvatar from './DiscussionAvatar';
import { TierBadge, VoteButton } from './Community';
export type Topic = {
  id: number;
  competition_id: number | null;
  scope: DiscussionScope;
  scope_id: number;
  scope_title: string | null;
  url: string;
  owner_id: number;
  title: string;
  owner: string;
  owner_tier?: string | null;
  created_at: string;
  last_activity: string;
  comment_count: number;
  votes: number;
  pinned: boolean;
  locked: boolean;
  bookmarked: boolean;
  voted: boolean;
  hidden?: boolean;
};
const scopeLabels: Record<DiscussionScope, string> = {
  competition: 'Competition',
  forum: 'Forum',
  dataset: 'Dataset',
  model: 'Model',
};
export default function DiscussionList({
  competitionId,
  scope,
  scopeId,
  scopeTitle,
  heading,
  user,
  signIn,
  initialQuery = '',
  initialSort = 'recent',
  pageSize,
}: {
  competitionId?: number;
  scope?: DiscussionScope;
  scopeId?: number;
  scopeTitle?: string;
  heading?: string;
  user: User | null;
  signIn: () => void;
  initialQuery?: string;
  initialSort?: string;
  pageSize?: number;
}) {
  const listScope = competitionId ? 'competition' : scope;
  const listScopeId = competitionId ?? scopeId;
  const scoped = listScope !== undefined && listScopeId !== undefined;
  const [query, setQuery] = useState(initialQuery);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState(initialSort);
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
  const [canPost, setCanPost] = useState(false);
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
      if (pageSize) params.set('limit', String(pageSize));
      if (listScope) params.set('scope', listScope);
      if (listScopeId !== undefined) params.set('scope_id', String(listScopeId));
      api<{
        items: Topic[];
        next_offset: number | null;
        can_pin: boolean;
        can_post: boolean;
      }>(`/competition-discussions?${params}`)
        .then((data) => {
          if (active) {
            setItems((old) =>
              offset
                ? [...old, ...data.items.filter((row) => !old.some((item) => item.id === row.id))]
                : data.items,
            );
            setNext(data.next_offset);
            setCanPin(data.can_pin);
            setCanPost(data.can_post);
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
  }, [listScope, listScopeId, query, filter, sort, unanswered, offset, revision, user?.id]);
  async function action(row: Topic, kind: 'bookmark' | 'pin') {
    if (!user) {
      signIn();
      return;
    }
    setMutating(true);
    setError('');
    try {
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
        <h2>{heading || (scoped ? 'Discussion' : 'Discussions')}</h2>
        {scoped && canPost && (
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
          {['all', 'owned', 'bookmarks', 'watching'].map((value) => (
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
              {
                (
                  {
                    all: 'All',
                    owned: 'Owned',
                    bookmarks: 'Bookmarks',
                    watching: 'Watching',
                  } as Record<string, string>
                )[value]
              }
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
          <option value="hot">Hot</option>
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
                  <a href={row.url}>
                    <h3>
                      {row.title}
                      {row.locked && (
                        <span className="topic-state" title="Locked">
                          <Lock size={14} aria-label="Locked" />
                        </span>
                      )}
                      {row.hidden && <span className="moderation-badge">Hidden</span>}
                    </h3>
                  </a>
                  <p>
                    {row.owner} <TierBadge tier={row.owner_tier} /> ·{' '}
                    {row.comment_count ? 'Last comment' : 'Posted'}{' '}
                    {new Date(row.last_activity).toLocaleDateString()}
                    {!scoped && row.scope_title && (
                      <>
                        {' · '}
                        <span className="topic-scope">
                          {scopeLabels[row.scope]}: {row.scope_title}
                        </span>
                      </>
                    )}
                  </p>
                </div>
                <div className="discussion-topic-actions">
                  <VoteButton
                    kind="competition-post"
                    id={row.id}
                    votes={row.votes}
                    voted={row.voted}
                    ownerId={row.owner_id}
                    user={user}
                    signIn={signIn}
                    label={row.title}
                  />
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
          <p>{scoped && canPost ? 'Start the first discussion.' : 'Try another search or filter.'}</p>
        </div>
      )}
      {next !== null && !busy && (
        <button className="button secondary" onClick={() => setOffset(next)}>
          Load more topics
        </button>
      )}
      {creating && listScope && listScopeId !== undefined && (
        <DiscussionCreate
          scope={listScope}
          scopeId={listScopeId}
          scopeTitle={scopeTitle}
          close={() => setCreating(false)}
        />
      )}
    </section>
  );
}
