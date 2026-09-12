import Markdown from './Markdown';
import { useEffect, useState } from 'react';
import { api } from './api';

export type Overview = {
  starts_at: string | null;
  ends_at: string | null;
  source_pages?: Record<string, string>;
  prize: string;
  description: string;
  prize_details: string;
  getting_started: string;
  evaluation: string;
  data_description: string;
  metric: string;
};
const localDate = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
export default function CompetitionOverview({
  id,
  organizer,
  changed,
}: {
  id: number;
  organizer: boolean;
  changed: () => void;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api<Overview>(`/competitions/${id}/overview`)
      .then((row) => {
        if (alive) setData(row);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [id]);
  if (!data) return <p role={error ? 'alert' : 'status'}>{error || 'Loading overview…'}</p>;
  return (
    <>
      <div className="metadata-heading">
        <h2>Overview</h2>
        {organizer && (
          <button className="button secondary" onClick={() => setEditing(!editing)}>
            {editing ? 'Cancel editing' : 'Edit overview'}
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {editing ? (
        <form
          className="metadata-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const payload = Object.fromEntries(form.entries());
            setBusy(true);
            setError('');
            try {
              const row = await api<Overview>(`/competitions/${id}/overview`, {
                method: 'PUT',
                body: JSON.stringify({
                  ...payload,
                  starts_at: payload.starts_at
                    ? new Date(String(payload.starts_at)).toISOString()
                    : null,
                  ends_at: new Date(String(payload.ends_at)).toISOString(),
                }),
              });
              setData(row);
              setEditing(false);
              changed();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>Dates use your local timezone. The end date is also the submission deadline.</p>
          <div className="metadata-two-columns">
            <label>
              Start date
              <input
                name="starts_at"
                type="datetime-local"
                defaultValue={localDate(data.starts_at)}
              />
            </label>
            <label>
              Submission deadline
              <input
                name="ends_at"
                type="datetime-local"
                required
                defaultValue={localDate(data.ends_at)}
              />
            </label>
          </div>
          <label>
            Prize summary
            <input name="prize" maxLength={80} defaultValue={data.prize} />
          </label>
          {(
            [
              ['description', 'Competition description'],
              ['prize_details', 'Prize details'],
              ['getting_started', 'How to participate'],
              ['evaluation', 'Evaluation details'],
              ['data_description', 'Data documentation'],
            ] as const
          ).map(([name, label]) => (
            <label key={name}>
              {label}
              <textarea
                aria-label={label}
                name={name}
                rows={5}
                defaultValue={data[name] || ''}
                required={name === 'description'}
                maxLength={name === 'prize_details' || name === 'evaluation' ? 10000 : 20000}
              />
            </label>
          ))}
          <button className="button" disabled={busy}>
            {busy ? 'Saving…' : 'Save overview'}
          </button>
        </form>
      ) : (
        <>
          <p className="competition-description">{data.description}</p>
          <div className="competition-overview-grid">
            <section>
              <h3>Competition period</h3>
              <dl className="metadata-facts">
                <dt>Starts</dt>
                <dd>
                  {data.starts_at
                    ? new Date(data.starts_at).toLocaleString()
                    : 'Start date not specified'}
                </dd>
                <dt>Submission deadline</dt>
                <dd>{data.ends_at ? new Date(data.ends_at).toLocaleString() : 'Ongoing'}</dd>
              </dl>
            </section>
            <section>
              <h3>Prizes</h3>
              <strong>{data.prize}</strong>
              <p className="competition-description">
                {data.prize_details || 'No additional prize details provided.'}
              </p>
            </section>
          </div>
          <section>
            <h3>How to participate</h3>
            <Markdown>
              {data.getting_started ||
                'Join, explore the data, train a model, and submit predictions on Leaderboard.'}
            </Markdown>
          </section>
          <section>
            <h3>Evaluation · {data.metric}</h3>
            <Markdown>{data.evaluation}</Markdown>
          </section>
          {data.source_pages?.['frequently asked questions'] && (
            <section>
              <h3>Frequently asked questions · Kaggle</h3>
              <Markdown>{data.source_pages['frequently asked questions']}</Markdown>
            </section>
          )}
        </>
      )}
    </>
  );
}
