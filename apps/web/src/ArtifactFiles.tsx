import { useEffect, useState } from 'react';
import { api } from './api';

type FileVersion = { id: number; path: string; size: number; sha256: string; created_at: string };

export default function ArtifactFiles({
  kind,
  id,
  owner,
  changed,
}: {
  kind: 'datasets' | 'models';
  id: number;
  owner: boolean;
  changed?: () => void;
}) {
  const [files, setFiles] = useState<FileVersion[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const base = `/assets/${kind}/${id}`;
  useEffect(() => {
    let active = true;
    api<FileVersion[]>(base)
      .then((rows) => {
        if (active) {
          setFiles(rows);
          setMore(rows.length === 50);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [base]);
  return (
    <section className="artifact-files">
      <h3>{kind === 'models' ? 'Model files' : 'Additional dataset files'}</h3>
      <p>
        Upload a new file or use the same path to add a version. Previous versions remain available.
        Each file can be up to 10 MB.
      </p>
      {kind === 'datasets' && (
        <p>
          New notebooks attach the original CSV and the latest version of each additional file.
          Existing notebooks keep their pinned input versions.
        </p>
      )}
      {owner && (
        <form
          className="metadata-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            setBusy(true);
            setError('');
            try {
              const row = await api<FileVersion>(base, {
                method: 'POST',
                body: new FormData(form),
              });
              setFiles((old) => [row, ...old]);
              form.reset();
              changed?.();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            File path
            <input name="path" required maxLength={240} placeholder="weights/model.bin" />
          </label>
          <label>
            Artifact file
            <input name="file" type="file" required />
          </label>
          <button className="button secondary" disabled={busy}>
            {busy ? 'Uploading…' : 'Upload file version'}
          </button>
        </form>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!files.length && <p>No additional files uploaded.</p>}
      <ul className="artifact-list">
        {files.map((file) => (
          <li key={file.id}>
            <a href={`/api${base}/${file.id}/download`}>{file.path}</a>
            <small>
              Version {file.id} · {file.size.toLocaleString()} bytes ·{' '}
              {new Date(file.created_at).toLocaleString()}
            </small>
            <small title={file.sha256}>SHA-256: {file.sha256.slice(0, 16)}…</small>
          </li>
        ))}
      </ul>
      {more && (
        <button
          className="button secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError('');
            try {
              const rows = await api<FileVersion[]>(`${base}?before=${files[files.length - 1].id}`);
              setFiles((old) => [...old, ...rows]);
              setMore(rows.length === 50);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Load older file versions
        </button>
      )}
    </section>
  );
}
