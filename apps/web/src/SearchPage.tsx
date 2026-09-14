import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { api, apiPage, type User } from './api';

export const searchTypes = [
  'competitions',
  'datasets',
  'notebooks',
  'models',
  'topics',
  'courses',
  'users',
] as const;
export type SearchType = (typeof searchTypes)[number];
const typeLabels: Record<SearchType, string> = {
  competitions: 'Competitions',
  datasets: 'Datasets',
  notebooks: 'Code',
  models: 'Models',
  topics: 'Discussions',
  courses: 'Courses',
  users: 'Users',
};
type Result = {
  type: SearchType;
  id: number;
  title: string;
  snippet: string;
  url: string;
  owner: string | null;
};
const PAGE_SIZE = 20;

/** `#search?q=...&type=...` */
export function searchRouteFromHash() {
  const match = location.hash.match(/^#search(?:\?(.*))?$/);
  if (!match) return null;
  const parameters = new URLSearchParams(match[1] || '');
  const type = parameters.get('type') || '';
  return {
    q: parameters.get('q') || '',
    type: (searchTypes as readonly string[]).includes(type) ? (type as SearchType) : null,
  };
}

export function searchHash(q: string, type?: SearchType | null) {
  const parameters = new URLSearchParams({ q });
  if (type) parameters.set('type', type);
  return `search?${parameters}`;
}

export default function SearchPage({
  q,
  type,
}: {
  q: string;
  type: SearchType | null;
  user: User | null;
}) {
  const [input, setInput] = useState(q);
  const [items, setItems] = useState<Result[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setInput(q), [q]);
  useEffect(() => {
    let active = true;
    setItems([]);
    setTotal(0);
    setError('');
    if (!q.trim()) {
      setCounts({});
      return;
    }
    setLoading(true);
    const parameters = new URLSearchParams({ q, limit: String(PAGE_SIZE) });
    if (type) parameters.set('type', type);
    Promise.all([
      apiPage<Result>(`/search?${parameters}`),
      api<Record<string, number>>(`/search/counts?${new URLSearchParams({ q })}`),
    ])
      .then(([page, typeCounts]) => {
        if (active) {
          setItems(page.items);
          setTotal(page.total);
          setCounts(typeCounts);
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
  }, [q, type]);
  const groups = type ? [type] : searchTypes.filter((kind) => items.some((row) => row.type === kind));
  return (
    <section className="search-page">
      <div className="eyebrow">SEARCH</div>
      <form
        className="search search-page-form"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          location.hash = searchHash(input.trim(), type);
        }}
      >
        <Search size={18} />
        <input
          aria-label="Search Arena"
          placeholder="Search competitions, datasets, code, models, discussions, courses and users"
          maxLength={100}
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <button className="button small">Search</button>
      </form>
      {q && (
        <nav className="search-types" aria-label="Result types">
          <a href={`#${searchHash(q)}`} aria-current={!type ? 'page' : undefined}>
            All {Object.values(counts).reduce((sum, value) => sum + value, 0)}
          </a>
          {searchTypes.map((kind) => (
            <a
              key={kind}
              href={`#${searchHash(q, kind)}`}
              aria-current={type === kind ? 'page' : undefined}
            >
              {typeLabels[kind]} {counts[kind] ?? 0}
            </a>
          ))}
        </nav>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!q.trim() && <p className="muted">Enter a word to search across Arena.</p>}
      {groups.map((kind) => (
        <section key={kind} className="search-group" aria-label={typeLabels[kind]}>
          <h2>{typeLabels[kind]}</h2>
          {items
            .filter((row) => row.type === kind)
            .map((row) => (
              <article key={`${row.type}-${row.id}`} className="search-result">
                <a href={row.url}>
                  <h3>{row.title}</h3>
                </a>
                <p className="muted">
                  {typeLabels[row.type]}
                  {row.owner ? ` · by ${row.owner}` : ''}
                </p>
                {row.snippet && <p>{row.snippet}</p>}
              </article>
            ))}
        </section>
      ))}
      {loading && <p role="status">Searching…</p>}
      {!loading && q.trim() && !items.length && !error && (
        <div className="empty">
          <Search />
          <h3>No results</h3>
          <p>Try a different word or result type.</p>
        </div>
      )}
      {!loading && items.length < total && (
        <div className="load-more-row">
          <span className="muted">
            Showing {items.length} of {total}
          </span>
          <button
            className="button secondary"
            onClick={async () => {
              setLoading(true);
              try {
                const parameters = new URLSearchParams({
                  q,
                  offset: String(items.length),
                  limit: String(PAGE_SIZE),
                });
                if (type) parameters.set('type', type);
                const page = await apiPage<Result>(`/search?${parameters}`);
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
        </div>
      )}
    </section>
  );
}
