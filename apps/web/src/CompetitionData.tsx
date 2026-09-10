import { useEffect, useState } from 'react';
import { Download, FileText, Folder, Lock } from 'lucide-react';
import { api, type Item } from './api';
import type { WorkItem } from './YourWork';
import type { Overview } from './CompetitionOverview';

type Column = { name: string; type: string; missing: number; description: string };
type DataFile = {
  id: number;
  path: string;
  role: string;
  description: string;
  license: string;
  source_url: string;
  source_dataset_id: number | null;
  row_count: number;
  size: number;
  sha256: string;
};
type Preview = DataFile & { columns: Column[]; preview: Record<string, string>[]; offset: number };
function FileTree({
  files,
  select,
  selected,
  prefix = '',
}: {
  files: DataFile[];
  select: (id: number) => void;
  selected: number | null;
  prefix?: string;
}) {
  const groups = [...new Set(files.map((file) => file.path.slice(prefix.length).split('/')[0]))];
  return (
    <ul className="competition-file-tree">
      {groups.map((name) => {
        const path = prefix + name;
        const file = files.find((row) => row.path === path);
        return (
          <li key={path}>
            {file ? (
              <button aria-pressed={selected === file.id} onClick={() => select(file.id)}>
                <FileText size={16} />
                <span>{name}</span>
              </button>
            ) : (
              <details open>
                <summary>
                  <Folder size={16} /> {name}
                </summary>
                <FileTree
                  files={files.filter((row) => row.path.startsWith(path + '/'))}
                  prefix={path + '/'}
                  select={select}
                  selected={selected}
                />
              </details>
            )}
          </li>
        );
      })}
    </ul>
  );
}
export default function CompetitionData({
  id,
  access,
  organizer,
  signedIn,
  signIn,
}: {
  id: number;
  access: boolean;
  organizer: boolean;
  signedIn: boolean;
  signIn: () => void;
}) {
  const [files, setFiles] = useState<DataFile[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [offset, setOffset] = useState(0);
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [datasets, setDatasets] = useState<Item[]>([]);
  const [source, setSource] = useState('');
  const base = `/competitions/${id}`;
  useEffect(() => {
    let alive = true;
    Promise.all([
      api<DataFile[]>(`${base}/files`),
      api<Overview>(`${base}/overview`),
      organizer ? api<WorkItem[]>('/work') : Promise.resolve([]),
    ])
      .then(([rows, overview, work]) => {
        if (!alive) return;
        setFiles(rows);
        setDescription(overview.data_description || '');
        setSelected((current) =>
          rows.some((row) => row.id === current) ? current : (rows[0]?.id ?? null),
        );
        setDatasets(work.filter((row) => row.work_kind === 'datasets'));
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id, organizer, revision]);
  useEffect(() => {
    let alive = true;
    setPreview(null);
    setError('');
    if (access && selected)
      api<Preview>(`${base}/files/${selected}?offset=${offset}`)
        .then((row) => {
          if (alive) setPreview(row);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    return () => {
      alive = false;
    };
  }, [id, access, selected, offset, revision]);
  const current = files.find((row) => row.id === selected);
  return (
    <>
      <h2>Competition data</h2>
      <p className="competition-description">{description}</p>
      <p className="muted">
        {files.length} files · {(files.reduce((sum, file) => sum + file.size, 0) / 1024).toFixed(1)}{' '}
        KB · CSV
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {organizer && (
        <details className="metadata-upload">
          <summary>Add competition data</summary>
          <form
            className="metadata-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const element = event.currentTarget;
              const form = new FormData(element);
              if (source) form.delete('file');
              else form.delete('dataset_id');
              setBusy(true);
              setError('');
              try {
                const row = await api<DataFile>(`${base}/files`, { method: 'POST', body: form });
                setSelected(row.id);
                setOffset(0);
                setRevision((v) => v + 1);
                element.reset();
                setSource('');
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Source dataset
              <select name="dataset_id" value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="">Upload a CSV</option>
                {datasets.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.title}
                  </option>
                ))}
              </select>
            </label>
            {!source && (
              <label>
                CSV file
                <input type="file" name="file" accept=".csv" required />
              </label>
            )}
            <label>
              File path
              <input
                name="path"
                placeholder="train/train.csv"
                pattern="[A-Za-z0-9_/-]+\.csv"
                required
                maxLength={255}
              />
            </label>
            <label>
              Purpose
              <select name="role">
                <option value="train">Training data</option>
                <option value="reference">Reference data</option>
              </select>
            </label>
            <label>
              Description
              <textarea name="description" maxLength={10000} rows={3} />
            </label>
            {!source && (
              <label>
                License
                <input name="license" maxLength={80} placeholder="For example, CC0-1.0" />
              </label>
            )}
            <p className="muted">
              Files are saved as snapshots. Existing evaluation features and submission templates
              stay consistent with scoring. Public source datasets remain public in Data Hub.
            </p>
            <button className="button" disabled={busy}>
              {busy ? 'Adding…' : 'Add file'}
            </button>
          </form>
        </details>
      )}
      {loading ? (
        <p role="status">Loading files…</p>
      ) : !files.length ? (
        <p>No files have been published.</p>
      ) : (
        <div className="competition-data-browser">
          <aside aria-label="Competition files">
            <h3>Files</h3>
            <FileTree
              files={files}
              selected={selected}
              select={(fileId) => {
                setSelected(fileId);
                setOffset(0);
              }}
            />
          </aside>
          <section className="competition-file-preview" aria-label="Dataset preview">
            <h3>{current?.path}</h3>
            <p className="competition-description">{current?.description}</p>
            <div className="metadata-file-facts">
              <span>{current?.role}</span>
              <span>{current?.row_count} rows</span>
              <span>{((current?.size || 0) / 1024).toFixed(1)} KB</span>
              <span>{current?.license || 'License not specified'}</span>
            </div>
            {current?.source_dataset_id && (
              <p className="muted">Source dataset #{current.source_dataset_id} · stored snapshot</p>
            )}
            {current?.source_url && /^https?:\/\//.test(current.source_url) && (
              <a href={current.source_url} target="_blank" rel="noreferrer">
                Original source
              </a>
            )}
            {!access ? (
              <div className="competition-data-locked">
                <Lock size={28} />
                <h3>Join to explore the data</h3>
                <p>
                  Join this competition using the button above to unlock previews, column details
                  and downloads.
                </p>
                {!signedIn && (
                  <button className="button" onClick={signIn}>
                    Sign in to join
                  </button>
                )}
              </div>
            ) : preview ? (
              <>
                <a className="button secondary" href={`/api${base}/files/${selected}/download`}>
                  <Download size={16} /> Download file
                </a>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        {preview.columns.map((column) => (
                          <th key={column.name}>{column.name}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.preview.map((row, index) => (
                        <tr key={index}>
                          {preview.columns.map((column) => (
                            <td key={column.name}>{row[column.name] || '—'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="metadata-pagination">
                  <button
                    className="button secondary"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - 25))}
                  >
                    Previous rows
                  </button>
                  <span>
                    Rows {offset + 1}–{offset + preview.preview.length} of {preview.row_count}
                  </span>
                  <button
                    className="button secondary"
                    disabled={offset + 25 >= preview.row_count}
                    onClick={() => setOffset(offset + 25)}
                  >
                    Next rows
                  </button>
                </div>
                <h3>Data dictionary</h3>
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
                      {preview.columns.map((column) => (
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
                {organizer && (
                  <details>
                    <summary>Edit file documentation</summary>
                    <form
                      className="metadata-form"
                      key={selected}
                      onSubmit={async (event) => {
                        event.preventDefault();
                        const form = new FormData(event.currentTarget);
                        setBusy(true);
                        setError('');
                        try {
                          await api(`${base}/files/${selected}`, {
                            method: 'PUT',
                            body: JSON.stringify({
                              description: form.get('description'),
                              column_descriptions: Object.fromEntries(
                                preview.columns.map((column, index) => [
                                  column.name,
                                  form.get(`column-${index}`),
                                ]),
                              ),
                            }),
                          });
                          setRevision((v) => v + 1);
                        } catch (e) {
                          setError((e as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <label>
                        File description
                        <textarea
                          name="description"
                          defaultValue={preview.description}
                          maxLength={10000}
                        />
                      </label>
                      {preview.columns.map((column, index) => (
                        <label key={column.name}>
                          {column.name}
                          <input
                            name={`column-${index}`}
                            defaultValue={column.description}
                            maxLength={2000}
                          />
                        </label>
                      ))}
                      <button className="button" disabled={busy}>
                        Save documentation
                      </button>
                    </form>
                  </details>
                )}
                <details>
                  <summary>File integrity</summary>
                  <p className="file-checksum">SHA-256: {preview.sha256}</p>
                </details>
              </>
            ) : (
              <p role="status">{error ? 'Preview unavailable' : 'Loading preview…'}</p>
            )}
          </section>
        </div>
      )}
    </>
  );
}
