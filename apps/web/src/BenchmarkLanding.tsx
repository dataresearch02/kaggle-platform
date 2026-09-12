import { useEffect, useRef } from 'react';
import {
  Plus,
  Search,
  ChevronDown,
  ArrowUpRight,
  BarChart3,
  Boxes,
  FlaskConical,
  BookOpen,
} from 'lucide-react';
import ProfilePhoto from './ProfilePhoto';
import BenchmarkCatalogMenu from './BenchmarkCatalogMenu';
import type { Asset, Collection } from './benchmarkTypes';
import type { Item } from './api';

export default function BenchmarkLanding({
  tab,
  setTab,
  q,
  setQ,
  owned,
  openYourWork,
  visibility,
  setVisibility,
  items,
  legacy,
  loading,
  create,
  openLegacy,
}: {
  tab: string;
  setTab: (tab: string) => void;
  q: string;
  setQ: (q: string) => void;
  owned: boolean;
  openYourWork: () => void;
  visibility: string;
  setVisibility: (v: string) => void;
  items: (Asset | Collection)[];
  legacy: Item[];
  loading: boolean;
  create: (kind: 'collection' | 'task' | 'model') => void;
  openLegacy: (row: Item) => void;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const click = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) menu.current?.removeAttribute('open');
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && menu.current?.open) {
        menu.current.open = false;
        menu.current.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('click', click);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('click', click);
      document.removeEventListener('keydown', key);
    };
  }, []);
  const name = tab === 'collections' ? 'benchmarks' : tab === 'legacy' ? 'CSV benchmarks' : tab;
  return (
    <>
      <header className="benchmark-hero">
        <div className="benchmark-hero-copy">
          <h1>Benchmarks</h1>
          <p>
            Discover benchmarks and leaderboards from the Arena community. Build reusable tasks and
            compare models on what matters to you.
          </p>
          <a
            className="benchmark-guide-link"
            href="https://www.kaggle.com/docs/benchmarks"
            target="_blank"
            rel="noreferrer"
          >
            <BookOpen size={17} /> About task-based benchmarks <ArrowUpRight size={15} />
          </a>
          <div className="benchmark-hero-actions">
            <details className="benchmark-create-menu" ref={menu}>
              <summary className="button">
                <Plus size={20} /> Create <ChevronDown size={16} />
              </summary>
              <div className="benchmark-create-options">
                {(
                  [
                    ['collection', 'Create benchmark', Boxes],
                    ['task', 'Create task', FlaskConical],
                  ] as const
                ).map(([kind, label, Icon]) => (
                  <button
                    key={kind}
                    onClick={() => {
                      if (menu.current) menu.current.open = false;
                      create(kind);
                    }}
                  >
                    <Icon size={18} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </details>
            <button className="button secondary" onClick={openYourWork}>
              Your Work
            </button>
          </div>
        </div>
        <svg className="benchmark-hero-art" viewBox="0 0 360 220" fill="none" aria-hidden="true">
          <ellipse cx="184" cy="196" rx="142" ry="12" fill="#edf3f1" />
          <path
            d="M63 170V45a10 10 0 0 1 10-10h222a10 10 0 0 1 10 10v125"
            fill="white"
            stroke="#273b36"
            strokeWidth="3"
          />
          <path d="M63 66h242" stroke="#273b36" strokeWidth="2" />
          <circle cx="79" cy="51" r="3" fill="#1c876e" />
          <circle cx="90" cy="51" r="3" fill="#8dbdaf" />
          <circle cx="101" cy="51" r="3" fill="#dbe9e4" />
          <rect x="87" y="122" width="24" height="34" rx="3" fill="#d6e8e2" />
          <rect x="123" y="100" width="24" height="56" rx="3" fill="#8dbdaf" />
          <rect x="159" y="82" width="24" height="74" rx="3" fill="#1c876e" />
          <path
            d="m210 90 8 8 16-18m-24 43 8 8 16-18m-24 43 8 8 16-18"
            stroke="#1c876e"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M248 91h30m-30 32h24m-24 33h30"
            stroke="#a0b3ad"
            strokeWidth="4"
            strokeLinecap="round"
          />
          <path
            d="M41 170h285l-15 18H57l-16-18Z"
            fill="#eaf1ee"
            stroke="#273b36"
            strokeWidth="3"
            strokeLinejoin="round"
          />
          <circle cx="309" cy="46" r="24" fill="#f4d75e" />
          <path
            d="m299 47 7 7 14-16"
            stroke="#273b36"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M32 109h15m-7-8v16m283 22h14m-7-7v14"
            stroke="#77b5a4"
            strokeWidth="3"
            strokeLinecap="round"
          />
        </svg>
      </header>
      <div className="benchmark-catalog-navigation">
        <nav className="benchmark-tabs" aria-label="Benchmark catalog">
          {[
            ['collections', 'Benchmarks'],
            ['tasks', 'Tasks'],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-current={tab === key ? 'page' : undefined}
              onClick={() => {
                setTab(key);
                setQ('');
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="benchmark-other-catalogs">
          <span>Also explore</span>
          <BenchmarkCatalogMenu
            value={tab}
            onSelect={(value) => {
              setTab(value);
              setQ('');
            }}
          />
        </div>
      </div>
      {tab !== 'legacy' && (
        <>
          <label className="benchmark-search-pill">
            <Search size={23} />
            <input
              aria-label={`Search ${name}`}
              placeholder={`Search ${name}`}
              value={q}
              maxLength={160}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <div className="benchmark-filter-pills" role="group" aria-label="Benchmark visibility">
            {[
              ['all', `All ${name}`],
              ['public', 'Public'],
              ['private', 'Private'],
            ].map(([key, label]) => (
              <button
                key={key}
                aria-pressed={visibility === key}
                onClick={() => setVisibility(key)}
              >
                {label}
              </button>
            ))}
            {owned && <span className="benchmark-owned-label">Showing your work</span>}
          </div>
        </>
      )}
      <div className="benchmark-section-heading">
        <h2>
          {owned ? 'Your ' : 'Explore '}
          {name}
        </h2>
        <p>
          {tab === 'collections'
            ? 'Compare real evaluation results across versioned tasks and models.'
            : tab === 'tasks'
              ? 'Find reusable evaluations to add to your next benchmark.'
              : tab === 'models'
                ? 'Explore local models and configured API models.'
                : 'Your existing prediction benchmarks, preserved in one place.'}
        </p>
      </div>
      <div className="benchmark-discovery-grid">
        {tab === 'legacy'
          ? legacy.map((row) => (
              <article className="benchmark-discovery-card" key={row.id}>
                <button className="text-button" onClick={() => openLegacy(row)}>
                  <h3>{row.title}</h3>
                </button>
                <p>{row.description}</p>
                <footer>CSV prediction benchmark</footer>
              </article>
            ))
          : items.map((row) => {
              const asset = 'kind' in row;
              const leaders = !asset ? row.top_models || [] : [];
              return (
                <article className="benchmark-discovery-card" key={row.id}>
                  <div className="benchmark-card-heading">
                    <a href={`#benchmarks/${asset ? `${row.kind}s/` : ''}${row.id}`}>
                      <h3>{row.title}</h3>
                    </a>
                    <span className="benchmark-card-avatar">
                      <ProfilePhoto
                        src={
                          row.owner ? `/api/profiles/${encodeURIComponent(row.owner)}/avatar` : null
                        }
                        alt={`${row.owner || 'Creator'} profile photo`}
                      />
                    </span>
                  </div>
                  <span className="benchmark-card-owner">{row.owner || 'Arena community'}</span>
                  <p>
                    {row.description ||
                      (asset
                        ? 'A reusable evaluation resource for the Arena community.'
                        : 'A collection of tasks for comparing model performance.')}
                  </p>
                  <span className="benchmark-card-meta">
                    {row.visibility} ·{' '}
                    {asset
                      ? `Version #${row.version_id}`
                      : `${row.tasks.length} tasks · ${row.models.length} models`}
                  </span>
                  {!asset && (
                    <div className="benchmark-card-results">
                      {leaders.length ? (
                        <>
                          <small>Top models</small>
                          {leaders.map((model, index) => (
                            <div className="benchmark-card-score" key={index}>
                              <div>
                                <span>{model.model}</span>
                                <strong>{(model.score * 100).toFixed(1)}%</strong>
                              </div>
                              <progress
                                value={model.score}
                                max={1}
                                aria-label={`${model.model} score`}
                              />
                            </div>
                          ))}
                        </>
                      ) : (
                        <div className="benchmark-card-empty">
                          <BarChart3 size={22} />
                          <span>No completed results yet</span>
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
      </div>
      {!loading && tab !== 'legacy' && !items.length && (
        <div className="benchmark-discovery-empty">
          <Search size={28} />
          <h3>No {name} found</h3>
          <p>Try a different search or filter, or create your own.</p>
        </div>
      )}
    </>
  );
}
