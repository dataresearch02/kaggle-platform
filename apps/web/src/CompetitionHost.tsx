import { useEffect, useState } from 'react';
import {
  api,
  apiPage,
  formatScore,
  type LeaderboardRow,
  type MetricInfo,
  type SubmissionRow,
  type Timeline,
} from './api';
import { MedalBadge, RankChange } from './CompetitionRules';

type HostState = Timeline & {
  id: number;
  has_deadline: boolean;
  metric: string;
  metric_k: number | null;
  metric_label: string;
  metric_direction: 'higher' | 'lower';
  max_daily_submissions: number;
  max_final_submissions: number;
  rules: string;
  rules_revision: number;
  evaluation_available: boolean;
  public_rows: number;
  private_rows: number;
  finalized_at: string | null;
  participants: number;
  submissions: number;
  rescorable: number;
};
type Rescore = { rescored: number; skipped: number; failed: number };
type Disqualification = {
  id: number;
  team_id: number | null;
  user_id: number | null;
  name: string;
  reason: string;
  actor: string | null;
  created_at: string;
};
const PAGE_SIZE = 25;
const localInput = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const isoOrNull = (value: FormDataEntryValue | null) =>
  value ? new Date(String(value)).toISOString() : null;
const rescoreText = (counts: Rescore) =>
  `Rescored ${counts.rescored} submissions; ${counts.skipped} without stored predictions kept their scores; ${counts.failed} failed validation.`;

export default function CompetitionHost({ id, changed }: { id: number; changed: () => void }) {
  const base = `/competitions/${id}`;
  const [state, setState] = useState<HostState | null>(null);
  const [metrics, setMetrics] = useState<MetricInfo[]>([]);
  const [metric, setMetric] = useState('');
  const [disqualifications, setDisqualifications] = useState<Disqualification[]>([]);
  const [rows, setRows] = useState<{ items: SubmissionRow[]; total: number }>({
    items: [],
    total: 0,
  });
  const [query, setQuery] = useState({ q: '', final: '', offset: 0 });
  const [shakeup, setShakeup] = useState<LeaderboardRow[]>([]);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let alive = true;
    Promise.all([
      api<HostState>(`${base}/host`),
      api<MetricInfo[]>('/metrics'),
      api<Disqualification[]>(`${base}/host/disqualifications`),
    ])
      .then(([host, registry, removed]) => {
        if (!alive) return;
        setState(host);
        setMetrics(registry);
        setMetric(host.metric);
        setDisqualifications(removed);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [id, revision]);
  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({ offset: String(query.offset), limit: String(PAGE_SIZE) });
    if (query.q) params.set('q', query.q);
    if (query.final) params.set('final', query.final);
    apiPage<SubmissionRow>(`${base}/host/submissions?${params}`)
      .then((page) => {
        if (alive) setRows(page);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [id, revision, query]);
  const ended = !!state?.ended;
  useEffect(() => {
    let alive = true;
    setShakeup([]);
    if (ended)
      apiPage<LeaderboardRow>(`${base}/leaderboard?board=private&limit=100`)
        .then((page) => {
          if (alive) setShakeup(page.items);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    return () => {
      alive = false;
    };
  }, [id, revision, ended]);
  async function run(action: () => Promise<string>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      setNotice(await action());
      setRevision((value) => value + 1);
      changed();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!state) return <p role={error ? 'alert' : 'status'}>{error || 'Loading host tools…'}</p>;
  const selected = metrics.find((row) => row.name === metric);
  const label = state.metric_label;
  return (
    <section className="competition-host">
      <h2>Host tools</h2>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="competition-notice" role="status">
          {notice}
        </p>
      )}
      <div className="pill-row">
        <span>{state.participants} participants</span>
        <span>
          {state.submissions} submissions · {state.rescorable} rescorable
        </span>
        <span>
          {state.private_rows
            ? `${state.public_rows} public / ${state.private_rows} private answer rows`
            : 'No private split: every row is public'}
        </span>
        <span>
          {!state.has_deadline
            ? 'No deadline'
            : state.ended
              ? state.finalized_at
                ? `Finalized ${new Date(state.finalized_at).toLocaleString()}`
                : 'Ended'
              : 'Running'}
        </span>
      </div>

      <section className="host-section">
        <h3>Timeline, limits and metric</h3>
        <form
          key={`settings-${revision}`}
          className="metadata-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void run(async () => {
              const timeline = (name: string) =>
                state.has_deadline ? isoOrNull(form.get(name)) : null;
              const result = await api<HostState & { rescore: Rescore | null }>(
                `${base}/host/settings`,
                {
                  method: 'PUT',
                  body: JSON.stringify({
                    starts_at: timeline('starts_at'),
                    entry_deadline: timeline('entry_deadline'),
                    merger_deadline: timeline('merger_deadline'),
                    ends_at: timeline('ends_at'),
                    max_daily_submissions: Number(form.get('max_daily_submissions')),
                    max_final_submissions: Number(form.get('max_final_submissions')),
                    metric,
                    metric_k: selected?.uses_k ? Number(form.get('metric_k')) || null : null,
                  }),
                },
              );
              return result.rescore
                ? `Settings saved. ${rescoreText(result.rescore)}`
                : 'Settings saved';
            });
          }}
        >
          {state.has_deadline ? (
            <>
              <p>
                Dates use your local timezone. Joining and forming teams close at the entry
                deadline, team changes at the merger deadline, and submissions at the end.
              </p>
              <div className="metadata-two-columns">
                <label>
                  Start
                  <input
                    name="starts_at"
                    type="datetime-local"
                    defaultValue={localInput(state.starts_at)}
                  />
                </label>
                <label>
                  End (final submission deadline)
                  <input
                    name="ends_at"
                    type="datetime-local"
                    required
                    defaultValue={localInput(state.ends_at)}
                  />
                </label>
                <label>
                  Entry deadline
                  <input
                    name="entry_deadline"
                    type="datetime-local"
                    defaultValue={localInput(state.entry_deadline)}
                  />
                </label>
                <label>
                  Team merger deadline
                  <input
                    name="merger_deadline"
                    type="datetime-local"
                    defaultValue={localInput(state.merger_deadline)}
                  />
                </label>
              </div>
            </>
          ) : (
            <p className="muted">
              This competition has no deadline, so it has no timeline, final ranking or medals.
            </p>
          )}
          <div className="metadata-two-columns">
            <label>
              Daily submissions per team or participant
              <input
                name="max_daily_submissions"
                type="number"
                min={1}
                max={100}
                required
                defaultValue={state.max_daily_submissions}
              />
            </label>
            <label>
              Final submissions
              <input
                name="max_final_submissions"
                type="number"
                min={1}
                max={10}
                required
                defaultValue={state.max_final_submissions}
              />
            </label>
            <label>
              Metric
              <select value={metric} onChange={(event) => setMetric(event.target.value)}>
                {metrics.map((row) => (
                  <option key={row.name} value={row.name}>
                    {row.title} — {row.direction} is better
                  </option>
                ))}
              </select>
            </label>
            {selected?.uses_k && (
              <label>
                K
                <input
                  name="metric_k"
                  type="number"
                  min={1}
                  max={100}
                  defaultValue={state.metric_k ?? 5}
                />
              </label>
            )}
          </div>
          {selected && (
            <small>
              {selected.input}. Formula: <code>{selected.formula}</code>. Changing the metric
              rescores every submission with stored predictions.
            </small>
          )}
          <button className="button" disabled={busy}>
            Save settings
          </button>
        </form>
      </section>

      <section className="host-section">
        <h3>Rules · revision {state.rules_revision}</h3>
        <form
          key={`rules-${revision}`}
          className="metadata-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void run(async () => {
              const result = await api<{ rules_revision: number }>(`${base}/rules`, {
                method: 'PUT',
                body: JSON.stringify({
                  content: String(form.get('content') || ''),
                  material: form.get('material') === 'on',
                }),
              });
              return `Rules saved (revision ${result.rules_revision})`;
            });
          }}
        >
          <label>
            Rules (Markdown)
            <textarea name="content" rows={8} maxLength={50000} defaultValue={state.rules} />
          </label>
          <label className="checkbox-label">
            <input type="checkbox" name="material" />
            Material change: every participant must accept the rules again before submitting
          </label>
          <button className="button secondary" disabled={busy}>
            Save rules
          </button>
        </form>
      </section>

      <section className="host-section">
        <h3>Answers, scoring and results</h3>
        {state.evaluation_available && (
          <form
            key={`solution-${revision}`}
            className="metadata-form"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              if (!form.get('public_fraction')) form.delete('public_fraction');
              void run(async () => {
                const result = await api<{ rescore: Rescore }>(`${base}/host/solution`, {
                  method: 'PUT',
                  body: form,
                });
                return `Answers replaced. ${rescoreText(result.rescore)}`;
              });
            }}
          >
            <label>
              Replacement answer CSV
              <input name="solution_file" type="file" accept=".csv" required />
              <small>
                id,prediction with the same IDs, optionally followed by a Usage column (Public or
                Private).
              </small>
            </label>
            <label>
              Public fraction when there is no Usage column (optional)
              <input
                name="public_fraction"
                type="number"
                min={0.01}
                max={0.99}
                step={0.01}
                placeholder="Keep the current split"
              />
            </label>
            <button className="button secondary" disabled={busy}>
              Replace answers and rescore
            </button>
          </form>
        )}
        <div className="button-row">
          <button
            className="button secondary"
            disabled={busy || !state.evaluation_available}
            onClick={() =>
              void run(async () =>
                rescoreText(await api<Rescore>(`${base}/host/rescore`, { method: 'POST' })),
              )
            }
          >
            Rescore all submissions
          </button>
          <button
            className="button secondary"
            disabled={busy || !state.ended || !state.has_deadline}
            title={state.ended ? undefined : 'Available after the competition ends'}
            onClick={() =>
              void run(async () => {
                const result = await api<{ teams: number; medals: Record<string, number> }>(
                  `${base}/host/finalize`,
                  { method: 'POST' },
                );
                return `Finalized ${result.teams} ranked teams: ${result.medals.gold} gold, ${result.medals.silver} silver and ${result.medals.bronze} bronze medals`;
              })
            }
          >
            Finalize now
          </button>
          <a className="button secondary" href={`/api${base}/host/leaderboard.csv?board=public`}>
            Export public leaderboard
          </a>
          <a className="button secondary" href={`/api${base}/host/leaderboard.csv?board=private`}>
            Export private leaderboard
          </a>
        </div>
      </section>

      <section className="host-section">
        <h3>All submissions</h3>
        <form
          className="host-filters"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setQuery({
              q: String(form.get('q') || ''),
              final: String(form.get('final') || ''),
              offset: 0,
            });
          }}
        >
          <label>
            Participant or team
            <input name="q" defaultValue={query.q} maxLength={80} />
          </label>
          <label>
            Final selection
            <select name="final" defaultValue={query.final}>
              <option value="">All</option>
              <option value="true">Selected</option>
              <option value="false">Not selected</option>
            </select>
          </label>
          <button className="button secondary">Filter</button>
        </form>
        {rows.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Submitter</th>
                  <th>Team</th>
                  <th>File</th>
                  <th>Submitted</th>
                  <th>Public {label}</th>
                  <th>Private {label}</th>
                  <th>Final</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.items.map((row) => (
                  <tr key={row.id}>
                    <td>{row.id}</td>
                    <td>{row.submitter}</td>
                    <td>{row.team_id ? `${row.team_name} (#${row.team_id})` : '—'}</td>
                    <td>{row.filename}</td>
                    <td>{new Date(row.created_at).toLocaleString()}</td>
                    <td>{formatScore(row.score)}</td>
                    <td>
                      {formatScore(row.private_score)}
                      {!row.has_predictions && <small> · not rescorable</small>}
                    </td>
                    <td>{row.final_selected ? 'Selected' : ''}</td>
                    <td>
                      {row.disqualified ? (
                        'Disqualified'
                      ) : (
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() => {
                            const name = row.team_id ? `team ${row.team_name}` : row.submitter;
                            const reason = window.prompt(`Reason for disqualifying ${name}`);
                            if (reason)
                              void run(async () => {
                                await api(`${base}/host/disqualifications`, {
                                  method: 'POST',
                                  body: JSON.stringify(
                                    row.team_id
                                      ? { team_id: row.team_id, reason }
                                      : { user_id: row.user_id, reason },
                                  ),
                                });
                                return `Disqualified ${name}; leaderboards and results were updated`;
                              });
                          }}
                        >
                          Disqualify
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No submissions match.</p>
        )}
        {rows.total > PAGE_SIZE && (
          <div className="load-more-row">
            <span className="muted">
              {query.offset + 1}–{Math.min(query.offset + PAGE_SIZE, rows.total)} of {rows.total}
            </span>
            <button
              className="button secondary"
              disabled={query.offset === 0}
              onClick={() => setQuery({ ...query, offset: Math.max(0, query.offset - PAGE_SIZE) })}
            >
              Previous
            </button>
            <button
              className="button secondary"
              disabled={query.offset + PAGE_SIZE >= rows.total}
              onClick={() => setQuery({ ...query, offset: query.offset + PAGE_SIZE })}
            >
              Next
            </button>
          </div>
        )}
      </section>

      <section className="host-section">
        <h3>Disqualifications</h3>
        {disqualifications.length ? (
          <ul className="host-list">
            {disqualifications.map((row) => (
              <li key={row.id}>
                <span>
                  <strong>{row.name}</strong>: {row.reason}{' '}
                  <small>
                    by {row.actor || 'a former host'} on{' '}
                    {new Date(row.created_at).toLocaleDateString()}
                  </small>
                </span>
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await api(`${base}/host/disqualifications/${row.id}`, { method: 'DELETE' });
                      return `${row.name} was reinstated`;
                    })
                  }
                >
                  Reinstate
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No participants or teams are disqualified.</p>
        )}
      </section>

      {state.ended && (
        <section className="host-section">
          <h3>Shake-up: public and private ranks</h3>
          {shakeup.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Final rank</th>
                    <th>Participant</th>
                    <th>Public rank</th>
                    <th>Change</th>
                    <th>Private {label}</th>
                    <th>Medal</th>
                  </tr>
                </thead>
                <tbody>
                  {shakeup.map((row) => (
                    <tr key={`${row.team_id ?? ''}-${row.username}`}>
                      <td>#{row.rank}</td>
                      <td>{row.username}</td>
                      <td>{row.public_rank ? `#${row.public_rank}` : '—'}</td>
                      <td>
                        <RankChange rank={row.rank} publicRank={row.public_rank} />
                      </td>
                      <td>{formatScore(row.score)}</td>
                      <td>
                        <MedalBadge medal={row.medal} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No ranked entries.</p>
          )}
        </section>
      )}
    </section>
  );
}
