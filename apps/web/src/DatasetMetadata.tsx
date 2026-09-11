import DatasetAccess from './DatasetAccess';
import ArtifactFiles from './ArtifactFiles';
import { useEffect, useState } from 'react';
import { api } from './api';
type Metadata = {
  source_url: string;
  citation: string;
  documentation: string;
  rows: number;
  sha256: string;
  columns: { name: string; type: string; missing: number; description: string }[];
};
export default function DatasetMetadata({ id, owner }: { id: number; owner: boolean }) {
  const [data, setData] = useState<Metadata | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api<Metadata>(`/datasets/${id}/metadata`)
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
  if (!data)
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p role="status">Loading dataset details…</p>
    );
  return (
    <section>
      {owner && <DatasetAccess id={id} />}
      <ArtifactFiles kind="datasets" id={id} owner={owner} />
      <div className="metadata-heading">
        <h3>Dataset documentation</h3>
        {owner && (
          <button className="button secondary" onClick={() => setEditing(!editing)}>
            {editing ? 'Cancel documentation edit' : 'Edit dataset documentation'}
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <p>
        {data.rows} rows · {data.columns.length} columns
      </p>
      {editing ? (
        <form
          className="metadata-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setBusy(true);
            setError('');
            try {
              const result = await api<Metadata>(`/datasets/${id}/metadata`, {
                method: 'PUT',
                body: JSON.stringify({
                  source_url: form.get('source_url') || null,
                  citation: form.get('citation'),
                  documentation: form.get('documentation'),
                  column_descriptions: Object.fromEntries(
                    data.columns.map((column, index) => [column.name, form.get(`column-${index}`)]),
                  ),
                }),
              });
              setData(result);
              setEditing(false);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Original source URL
            <input name="source_url" type="url" defaultValue={data.source_url} />
          </label>
          <label>
            Citation
            <textarea name="citation" defaultValue={data.citation} maxLength={10000} />
          </label>
          <label>
            Dataset documentation
            <textarea name="documentation" defaultValue={data.documentation} maxLength={20000} />
          </label>
          {data.columns.map((column, index) => (
            <label key={column.name}>
              {column.name}
              <input name={`column-${index}`} defaultValue={column.description} maxLength={2000} />
            </label>
          ))}
          <button className="button" disabled={busy}>
            Save dataset documentation
          </button>
        </form>
      ) : (
        <>
          {data.source_url && /^https?:\/\//.test(data.source_url) && (
            <a href={data.source_url} target="_blank" rel="noreferrer">
              Original source
            </a>
          )}
          <p className="competition-description">{data.documentation}</p>
          <p className="competition-description">{data.citation}</p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Inferred type</th>
                  <th>Missing values</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {data.columns.map((column) => (
                  <tr key={column.name}>
                    <td>{column.name}</td>
                    <td>{column.type}</td>
                    <td>{column.missing}</td>
                    <td>{column.description || 'Not documented yet'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
