import { useEffect, useRef, useState } from 'react';
import { Bookmark, Code2, Search, ArrowUpRight } from 'lucide-react';
import { api, type User } from './api';
import NewNotebook from './NewNotebook';
export type CodeSummary = {
  id: number;
  title: string;
  description: string;
  owner_id: number;
  owner: string;
  created_at: string;
  bookmarked: boolean;
};
type CodeBatch = { items: CodeSummary[]; next_cursor: number | null };
const filters = [
  ['all', 'All'],
  ['your-work', 'Your work'],
  ['shared', 'Shared with you'],
  ['bookmarks', 'Bookmarks'],
] as const;
export default function CodeList({
  competitionId,
  user,
  signIn,
  joined = false,
}: {
  competitionId?: number;
  user: User | null;
  signIn: () => void;
  joined?: boolean;
}) {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [revision, setRevision] = useState(0);
  const [owned, setOwned] = useState<CodeSummary[]>([]);
  const [ownSearch, setOwnSearch] = useState('');
  const [selected, setSelected] = useState('');
  const [shareOpen, setShareOpen] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (!competitionId || !user || !shareOpen) return;
    let active = true;
    const timer = setTimeout(() => {
      api<CodeBatch>(`/code?filter=your-work&limit=50&q=${encodeURIComponent(ownSearch)}`)
        .then((data) => {
          if (active) setOwned(data.items);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [competitionId, user?.id, ownSearch, shareOpen]);
  return (
    <section className="code-library">
      <div className="metadata-heading">
        <div>
          <h2>{competitionId ? 'Competition code' : 'Codes'}</h2>
          <p className="muted">
            Explore published notebooks, learn from results, and fork your own copy.
          </p>
        </div>
        {competitionId && (
          <div className="button-row">
            <button
              className="button"
              disabled={!user || !joined}
              title={!joined ? 'Join this competition to create a notebook' : undefined}
              onClick={() => setCreating(true)}
            >
              New notebook
            </button>
            <button
              className="button secondary"
              onClick={() => (user ? setShareOpen(!shareOpen) : signIn())}
            >
              Use existing code
            </button>
          </div>
        )}
      </div>
      {competitionId && !joined && (
        <p className="muted">Join this competition to create a notebook for it.</p>
      )}
      {creating && user && joined && (
        <NewNotebook
          competitionId={competitionId}
          close={() => {
            setCreating(false);
            setRevision((value) => value + 1);
          }}
          saved={() => {
            setFilter('your-work');
            setQuery('');
            setSearch('');
            setRevision((value) => value + 1);
          }}
        />
      )}
      {shareOpen && user && (
        <form
          className="competition-share"
          onSubmit={(event) => {
            event.preventDefault();
            window.location.hash = `code/${selected}/edit?competition=${competitionId}`;
          }}
        >
          <label>
            Find your code
            <input
              value={ownSearch}
              onChange={(e) => setOwnSearch(e.target.value)}
              placeholder="Search your saved code"
            />
          </label>
          <label>
            Your saved code
            <select required value={selected} onChange={(e) => setSelected(e.target.value)}>
              <option value="">Choose your saved work</option>
              {owned.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title}
                </option>
              ))}
            </select>
          </label>
          <button className="button secondary" disabled={!selected || !joined}>
            Open to commit
          </button>
        </form>
      )}
      <div className="code-library-controls">
        <div className="code-library-filters" role="tablist" aria-label="Code filters">
          {filters.map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="code-search">
          <Search size={18} />
          <input
            aria-label="Search codes"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search codes"
            maxLength={160}
          />
        </label>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {filter !== 'all' && !user ? (
        <div className="empty">
          <h3>Sign in to see {filters.find(([value]) => value === filter)?.[1].toLowerCase()}</h3>
          <button className="button" onClick={signIn}>
            Sign in
          </button>
        </div>
      ) : (
        <CodeRows
          key={`${competitionId}-${filter}-${search}-${user?.id}-${revision}`}
          competitionId={competitionId}
          filter={filter}
          search={search}
          user={user}
          signIn={signIn}
        />
      )}
    </section>
  );
}
function CodeRows({
  competitionId,
  filter,
  search,
  user,
  signIn,
}: {
  competitionId?: number;
  filter: string;
  search: string;
  user: User | null;
  signIn: () => void;
}) {
  const [rows, setRows] = useState<CodeSummary[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [bookmarkError, setBookmarkError] = useState('');
  const [pending, setPending] = useState<number[]>([]);
  const sentinel = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  const mounted = useRef(false);
  const generation = useRef(0);
  async function load(after: number | null) {
    if (busy.current) return;
    const version = generation.current;
    busy.current = true;
    setLoading(true);
    setError('');
    const query = new URLSearchParams({ filter, q: search, limit: '20' });
    if (competitionId) query.set('competition_id', String(competitionId));
    if (after) query.set('cursor', String(after));
    try {
      const batch = await api<CodeBatch>(`/code?${query}`);
      if (!mounted.current || version !== generation.current) return;
      setRows((previous) => [
        ...new Map([...previous, ...batch.items].map((row) => [row.id, row])).values(),
      ]);
      setCursor(batch.next_cursor);
    } catch (e) {
      if (mounted.current && version === generation.current) setError((e as Error).message);
    } finally {
      if (mounted.current && version === generation.current) {
        busy.current = false;
        setLoading(false);
      }
    }
  }
  useEffect(() => {
    mounted.current = true;
    busy.current = false;
    void load(null);
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    if (!cursor || loading || error || !sentinel.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void load(cursor);
      },
      { rootMargin: '240px' },
    );
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [cursor, loading, error]);
  return (
    <>
      {bookmarkError && (
        <p className="error" role="alert">
          {bookmarkError}
        </p>
      )}
      <div className="code-result-list">
        {rows.map((row) => (
          <article className="code-result-row" key={row.id}>
            <div className="code-result-icon">
              <Code2 size={24} />
            </div>
            <div className="code-result-content">
              <h3>
                <a
                  href={`#code/${row.id}${user?.id === row.owner_id ? '/edit' : ''}${competitionId ? `?competition=${competitionId}` : ''}`}
                >
                  {row.title} <ArrowUpRight size={15} />
                </a>
              </h3>
              <p className="code-result-byline">
                By {row.owner} · {new Date(row.created_at).toLocaleDateString()} · Python notebook
              </p>
              <p className="code-result-description">
                {row.description || 'Explore this notebook and its published results.'}
              </p>
            </div>
            <button
              className="code-bookmark"
              aria-label={`${row.bookmarked ? 'Remove bookmark for' : 'Bookmark'} ${row.title}`}
              aria-pressed={row.bookmarked}
              disabled={pending.includes(row.id)}
              onClick={async () => {
                if (!user) {
                  signIn();
                  return;
                }
                setPending((values) => [...values, row.id]);
                setBookmarkError('');
                try {
                  const result = await api<{ bookmarked: boolean }>(`/code/${row.id}/bookmark`, {
                    method: row.bookmarked ? 'DELETE' : 'PUT',
                  });
                  if (mounted.current)
                    setRows((values) =>
                      filter === 'bookmarks' && !result.bookmarked
                        ? values.filter((value) => value.id !== row.id)
                        : values.map((value) =>
                            value.id === row.id ? { ...value, ...result } : value,
                          ),
                    );
                } catch (e) {
                  if (mounted.current) setBookmarkError((e as Error).message);
                } finally {
                  if (mounted.current)
                    setPending((values) => values.filter((value) => value !== row.id));
                }
              }}
            >
              <Bookmark size={20} fill={row.bookmarked ? 'currentColor' : 'none'} />
            </button>
          </article>
        ))}
      </div>
      {!loading && !rows.length && !error && (
        <div className="empty">
          <h3>No codes found</h3>
          <p>
            {filter === 'shared'
              ? 'Code shared with your username will appear here.'
              : filter === 'bookmarks'
                ? 'Bookmark a notebook to find it here later.'
                : 'Try a different search or share a notebook with this competition.'}
          </p>
        </div>
      )}
      <div ref={sentinel} className="code-load-more">
        {loading ? (
          <p role="status">Loading codes…</p>
        ) : error ? (
          <>
            <p className="error" role="alert">
              {error}
            </p>
            <button className="button secondary" onClick={() => void load(cursor)}>
              Retry loading codes
            </button>
          </>
        ) : cursor ? (
          <button className="button secondary" onClick={() => void load(cursor)}>
            Load more codes
          </button>
        ) : rows.length > 0 ? (
          <p className="muted">All matching codes loaded</p>
        ) : null}
      </div>
    </>
  );
}
