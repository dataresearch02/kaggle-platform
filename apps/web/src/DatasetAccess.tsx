import { useEffect, useState } from 'react';
import { api } from './api';

type Access = { visibility: 'private' | 'public'; shares: { id: number; username: string }[] };
export default function DatasetAccess({ id }: { id: number }) {
  const [data, setData] = useState<Access | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function load() {
    setData(await api<Access>(`/datasets/${id}/access`));
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, [id]);
  async function change(path: string, method: string, body?: object) {
    setBusy(true);
    setError('');
    try {
      await api(`/datasets/${id}/${path}`, {
        method,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="dataset-access">
      <h3>Visibility and sharing</h3>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <label>
            Dataset visibility
            <select
              value={data.visibility}
              disabled={busy}
              onChange={(event) => {
                const visibility = event.target.value;
                if (
                  visibility === 'public' &&
                  !window.confirm(
                    'Make this dataset publicly downloadable? Existing copies cannot be recalled.',
                  )
                )
                  return;
                void change('access', 'PUT', { visibility });
              }}
            >
              <option value="private">Private — you and invited users</option>
              <option value="public">Public — everyone</option>
            </select>
          </label>
          <p>
            Changing access does not remove copies already downloaded or attached to a notebook or
            competition.
          </p>
          <form
            className="metadata-form"
            onSubmit={(event) => {
              event.preventDefault();
              void change('shares', 'POST', {
                username: new FormData(event.currentTarget).get('username'),
              });
            }}
          >
            <label>
              Share dataset with username
              <input name="username" required minLength={3} maxLength={40} />
            </label>
            <button className="button secondary" disabled={busy}>
              Grant read access
            </button>
          </form>
          <ul>
            {data.shares.map((person) => (
              <li key={person.id}>
                {person.username}{' '}
                <button
                  className="button secondary small"
                  disabled={busy}
                  onClick={() => void change(`shares/${person.id}`, 'DELETE')}
                >
                  Revoke {person.username}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
