import { useEffect, useState } from 'react';
import { ArrowLeft, Plus, Play, Download, Share2 } from 'lucide-react';
import { api, type User, type Item } from './api';
import Markdown from './Markdown';
import BenchmarkDrawer from './BenchmarkDrawer';
import BenchmarkLanding from './BenchmarkLanding';
import { type Asset, type Collection, type Board, type Run } from './benchmarkTypes';

type Row = Asset | Collection;
const route = () => location.hash.match(/^#benchmarks\/(?:(tasks|models)\/)?(\d+)$/);
const score = (value: number | null) => (value === null ? '—' : `${(value * 100).toFixed(2)}%`);
export default function BenchmarkHub({
  user,
  signIn,
  creating,
  closeCreate,
  openLegacy,
  yourWork,
}: {
  user: User | null;
  signIn: () => void;
  creating: boolean;
  closeCreate: () => void;
  openLegacy: (row: Item) => void;
  yourWork: () => void;
}) {
  const [locationRoute, setRoute] = useState(route);
  const [tab, setTab] = useState('collections');
  const [detailTab, setDetailTab] = useState('Overview');
  const [q, setQ] = useState('');
  const owned = false;
  const [visibility, setVisibility] = useState('all');
  const [items, setItems] = useState<Row[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [legacy, setLegacy] = useState<Item[]>([]);
  const [detail, setDetail] = useState<Row | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runNext, setRunNext] = useState<number | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [drawer, setDrawer] = useState<{
    kind: 'collection' | 'task' | 'model';
    item?: Row;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState<number | null>(null);
  useEffect(() => {
    const change = () => {
      setRoute(route());
      setSelectedRun(null);
      setDetailTab('Overview');
      setVersion(null);
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => {
    if (creating) {
      setDrawer({ kind: 'collection' });
      closeCreate();
    }
  }, [creating, closeCreate]);
  const id = locationRoute ? Number(locationRoute[2]) : null;
  const assetRoute = locationRoute?.[1];
  const collection = !assetRoute ? (detail as Collection | null) : null;
  const isOwner = !!user && detail?.owner_id === user.id;
  const listingPath = `/benchmark-hub/${tab === 'collections' ? 'collections?' : `assets?kind=${tab === 'tasks' ? 'task' : 'model'}&`}q=${encodeURIComponent(q)}&owned=${owned}&visibility=${visibility}`;
  useEffect(() => {
    let active = true;
    setError('');
    setLoading(true);
    setDetail(null);
    setItems([]);
    setRuns([]);
    setBoard(null);
    const timer = setTimeout(
      async () => {
        try {
          if (id) {
            const row = await api<Row>(
              `/benchmark-hub/${assetRoute ? 'assets' : 'collections'}/${id}`,
            );
            if (active) setDetail(row);
            if (!assetRoute) {
              const [b, r] = await Promise.all([
                api<Board>(`/benchmark-hub/collections/${id}/leaderboard`),
                api<{ items: Run[]; next_cursor: number | null }>(
                  `/benchmark-hub/collections/${id}/runs`,
                ),
              ]);
              if (active) {
                setBoard(b);
                setRuns(r.items);
                setRunNext(r.next_cursor);
              }
            }
          } else if (tab === 'legacy') {
            const rows = await api<Item[]>('/benchmarks');
            if (active) setLegacy(rows);
          } else {
            const batch = await api<{ items: Row[]; next_cursor: number | null }>(listingPath);
            if (active) {
              setItems(batch.items);
              setNext(batch.next_cursor);
            }
          }
        } catch (e) {
          if (active) setError((e as Error).message);
        } finally {
          if (active) setLoading(false);
        }
      },
      q ? 180 : 0,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, assetRoute, listingPath, tab, revision, user?.id]);
  useEffect(() => {
    if (!id || assetRoute || !runs.some((r) => ['queued', 'running'].includes(r.status))) return;
    let active = true;
    const timer = setInterval(async () => {
      try {
        const batch = await api<{ items: Run[]; next_cursor: number | null }>(
          `/benchmark-hub/collections/${id}/runs`,
        );
        if (!active) return;
        const b = await api<Board>(`/benchmark-hub/collections/${id}/leaderboard`);
        if (!active) return;
        setBoard(b);
        setRuns(batch.items);
        setRunNext(batch.next_cursor);
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    }, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id, assetRoute, runs.some((r) => ['queued', 'running'].includes(r.status))]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function create(kind: 'collection' | 'task' | 'model') {
    if (!user) signIn();
    else setDrawer({ kind });
  }
  function link(row: Row) {
    return `#benchmarks/${'kind' in row ? `${row.kind}s/` : ''}${row.id}`;
  }
  const asset = assetRoute ? (detail as Asset | null) : null;
  const assetVersion = asset?.versions?.find((v) => v.id === version) || asset?.versions?.[0];
  return (
    <section className="benchmark-hub">
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {id ? (
        <>
          <a className="discussion-back" href="#benchmarks">
            <ArrowLeft size={18} /> All benchmarks
          </a>
          {detail && (
            <>
              <header className="benchmark-heading">
                <div>
                  <small>
                    {asset
                      ? `${asset.kind} · version #${assetVersion?.id}`
                      : 'Benchmark collection'}{' '}
                    · {detail.visibility}
                  </small>
                  <h1>{detail.title}</h1>
                </div>
                <div className="button-row">
                  <button
                    className="button secondary"
                    onClick={() =>
                      void action(async () => {
                        await navigator.clipboard.writeText(location.href);
                      })
                    }
                  >
                    <Share2 size={16} /> Copy link
                  </button>
                  {isOwner && (
                    <button
                      className="button secondary"
                      onClick={() =>
                        setDrawer({ kind: asset ? asset.kind : 'collection', item: detail })
                      }
                    >
                      Edit {asset ? asset.kind : 'benchmark'}
                    </button>
                  )}
                  {isOwner && collection && (
                    <button
                      className="button"
                      disabled={
                        busy ||
                        !collection.tasks.length ||
                        !collection.models.length ||
                        runs.some((r) => ['queued', 'running'].includes(r.status))
                      }
                      onClick={() =>
                        void action(async () => {
                          const r = await api<Run>(`/benchmark-hub/collections/${id}/runs`, {
                            method: 'POST',
                          });
                          setRuns((old) => [r, ...old]);
                          setDetailTab('Results');
                        })
                      }
                    >
                      <Play size={16} /> Run evaluation
                    </button>
                  )}
                </div>
              </header>
              {asset ? (
                <>
                  <Markdown>{asset.description}</Markdown>
                  <label>
                    Version
                    <select
                      value={assetVersion?.id}
                      onChange={(e) => setVersion(Number(e.target.value))}
                    >
                      {asset.versions?.map((v) => (
                        <option key={v.id} value={v.id}>
                          Version #{v.id} · {v.digest.slice(0, 12)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <h2>Python source</h2>
                  <pre className="benchmark-code">{assetVersion?.source}</pre>
                  {asset.kind === 'task' && (
                    <>
                      <h2>Evaluation cases</h2>
                      <pre className="benchmark-code">
                        {JSON.stringify(assetVersion?.cases, null, 2)}
                      </pre>
                    </>
                  )}
                  <p>Add this {asset.kind} to a benchmark to evaluate and compare models.</p>
                </>
              ) : (
                collection && (
                  <>
                    <nav className="benchmark-tabs" aria-label="Benchmark sections">
                      {['Overview', 'Tasks', 'Models', 'Results'].map((t) => (
                        <button
                          key={t}
                          aria-current={detailTab === t ? 'page' : undefined}
                          onClick={() => {
                            setDetailTab(t);
                            setSelectedRun(null);
                          }}
                        >
                          {t}
                        </button>
                      ))}
                    </nav>
                    {detailTab === 'Overview' && (
                      <>
                        <Markdown>
                          {collection.description ||
                            'Add tasks and models, then run an evaluation to build this benchmark’s leaderboard.'}
                        </Markdown>
                        <div className="benchmark-summary">
                          <strong>{collection.tasks.length} tasks</strong>
                          <strong>{collection.models.length} models</strong>
                          <span>CPU · offline · 2 GB · five-minute run limit</span>
                        </div>
                        <p>
                          Scores are the equal-weight mean of task scores. Models must finish every
                          task to rank. Results use immutable task and model versions.
                        </p>
                      </>
                    )}
                    {['Tasks', 'Models'].includes(detailTab) && (
                      <div className="benchmark-catalog">
                        {(detailTab === 'Tasks'
                          ? collection.task_details
                          : collection.model_details
                        ).map((a) => (
                          <article key={a.version_id}>
                            <a href={link(a)}>
                              <h3>{a.title}</h3>
                            </a>
                            <p>{a.description}</p>
                            <small>
                              Version #{a.version_id} · {a.digest.slice(0, 12)}
                            </small>
                          </article>
                        ))}
                        {isOwner && (
                          <button
                            className="button secondary"
                            onClick={() => setDrawer({ kind: 'collection', item: collection })}
                          >
                            <Plus size={16} /> Add or remove {detailTab.toLowerCase()}
                          </button>
                        )}
                      </div>
                    )}
                    {(detailTab === 'Overview' || detailTab === 'Results') && (
                      <>
                        <div className="benchmark-heading">
                          <h2>Leaderboard</h2>
                          <div className="button-row">
                            <a
                              className="button secondary"
                              href={`/api/benchmark-hub/collections/${id}/leaderboard?format=csv`}
                              download
                            >
                              <Download size={16} /> CSV
                            </a>
                            <a
                              className="button secondary"
                              href={`/api/benchmark-hub/collections/${id}/leaderboard`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              JSON
                            </a>
                          </div>
                        </div>
                        <div className="benchmark-table">
                          <table>
                            <thead>
                              <tr>
                                <th>Rank</th>
                                <th>Model</th>
                                <th>Score</th>
                                <th>Completed tasks</th>
                                {collection.task_details.map((t) => (
                                  <th key={t.version_id}>{t.title}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {board?.items.map((r) => (
                                <tr key={r.model_version_id}>
                                  <td>{r.rank ?? '—'}</td>
                                  <td>
                                    {r.model} <small>v{r.model_version_id}</small>
                                  </td>
                                  <td>{score(r.score)}</td>
                                  <td>
                                    {r.completed_tasks}/{r.total_tasks}
                                  </td>
                                  {collection.tasks.map((t) => (
                                    <td key={t}>
                                      {score(
                                        r.tasks.find((c) => c.task_version_id === t)?.score ?? null,
                                      )}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        {!board?.items.length && (
                          <p>No completed evaluations for these task and model versions yet.</p>
                        )}
                      </>
                    )}
                    {detailTab === 'Results' && (
                      <>
                        <h2>Evaluation history</h2>
                        <p>
                          Previous configurations remain in history; only matching versions appear
                          in the current leaderboard.
                        </p>
                        {runs.map((r) => (
                          <div className="benchmark-run" key={r.id}>
                            <button
                              className="text-button"
                              onClick={() =>
                                void action(async () => {
                                  setSelectedRun(await api<Run>(`/benchmark-hub/runs/${r.id}`));
                                })
                              }
                            >
                              Run #{r.id} · {r.status} · {new Date(r.created_at).toLocaleString()}
                              {r.fingerprint !== collection.fingerprint
                                ? ' · Previous configuration'
                                : ''}
                            </button>
                            {isOwner && ['queued', 'running'].includes(r.status) && (
                              <button
                                className="button secondary"
                                disabled={busy}
                                onClick={() =>
                                  void action(async () => {
                                    await api(`/benchmark-hub/runs/${r.id}/cancel`, {
                                      method: 'POST',
                                    });
                                    setRevision((v) => v + 1);
                                  })
                                }
                              >
                                Cancel run
                              </button>
                            )}
                            {r.error && <p className="error">{r.error}</p>}
                          </div>
                        ))}
                        {runNext && (
                          <button
                            className="button secondary"
                            onClick={() =>
                              void action(async () => {
                                const batch = await api<{
                                  items: Run[];
                                  next_cursor: number | null;
                                }>(`/benchmark-hub/collections/${id}/runs?before=${runNext}`);
                                setRuns((old) => [...old, ...batch.items]);
                                setRunNext(batch.next_cursor);
                              })
                            }
                          >
                            Load more runs
                          </button>
                        )}
                        {selectedRun && (
                          <section aria-label="Evaluation details">
                            <h2>Run #{selectedRun.id} details</h2>
                            <p>{selectedRun.error}</p>
                            {selectedRun.results?.map((r) => (
                              <details key={`${r.model_version_id}-${r.task_version_id}`}>
                                <summary>
                                  {r.model} / {r.task} · {r.status} · {score(r.score)} ·{' '}
                                  {r.duration_ms} ms
                                </summary>
                                {r.error && <p className="error">{r.error}</p>}
                                {r.cases.map((c) => (
                                  <article className="benchmark-case" key={c.index}>
                                    <h4>
                                      Case {c.index + 1} · {score(c.score)} · {c.duration_ms} ms
                                    </h4>
                                    <pre>{JSON.stringify(c.input, null, 2)}</pre>
                                    {c.outputs.map((o, i) => (
                                      <pre key={i}>{JSON.stringify(o, null, 2)}</pre>
                                    ))}
                                    {c.error && <p className="error">{c.error}</p>}
                                  </article>
                                ))}
                              </details>
                            ))}
                            <h3>Logs</h3>
                            <pre className="benchmark-code">
                              {selectedRun.logs || 'No log output.'}
                            </pre>
                          </section>
                        )}
                      </>
                    )}
                  </>
                )
              )}
            </>
          )}
        </>
      ) : (
        <>
          <BenchmarkLanding
            tab={tab}
            setTab={setTab}
            q={q}
            setQ={setQ}
            owned={owned}
            openYourWork={yourWork}
            visibility={visibility}
            setVisibility={setVisibility}
            items={items}
            legacy={legacy}
            loading={loading}
            create={create}
            openLegacy={openLegacy}
          />
          {next && tab !== 'legacy' && (
            <button
              className="button secondary"
              onClick={() =>
                void action(async () => {
                  const batch = await api<{ items: Row[]; next_cursor: number | null }>(
                    `${listingPath}&before=${next}`,
                  );
                  setItems((old) => [...old, ...batch.items]);
                  setNext(batch.next_cursor);
                })
              }
            >
              Load more
            </button>
          )}
        </>
      )}
      {loading && <p role="status">Loading benchmarks…</p>}
      {drawer && (
        <BenchmarkDrawer
          key={`${drawer.kind}-${drawer.item?.id}`}
          {...drawer}
          close={() => setDrawer(null)}
          saved={(id) => {
            location.hash = `benchmarks/${drawer.kind === 'collection' ? '' : `${drawer.kind}s/`}${id}`;
            setDrawer(null);
            setRevision((v) => v + 1);
          }}
        />
      )}
    </section>
  );
}
