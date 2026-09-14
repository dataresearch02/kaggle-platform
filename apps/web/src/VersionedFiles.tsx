import { useEffect, useState } from 'react';
import { Download, FileText, History, Trash2 } from 'lucide-react';
import { api, apiPage, formatBytes, type VersionFile, type VersionInfo } from './api';
import ChunkedUploader from './ChunkedUploader';
import FilePreview, { type PreviewData } from './FilePreview';
import './versions.css';

const FILES_PAGE = 100;
const typeLabels: Record<string, string> = {
  table: 'Table',
  json: 'JSON',
  jsonl: 'JSON Lines',
  markdown: 'Markdown',
  text: 'Text',
  image: 'Image',
  npy: 'NumPy array',
  zip: 'ZIP archive',
  parquet: 'Parquet',
  unsafe: 'Download only',
  binary: 'Binary',
};
const when = (value: string | null) => (value ? new Date(value).toLocaleString() : '');

/**
 * Files and version history of a dataset (`/datasets/<id>`) or model variation
 * (`/models/<id>/variations/<variationId>`), with the draft editor for managers.
 */
export default function VersionedFiles({
  scope,
  fileBase,
  manage,
  label,
  changed,
}: {
  scope: string;
  fileBase: string;
  manage: boolean;
  label: 'dataset' | 'model variation';
  changed?: () => void;
}) {
  const [versions, setVersions] = useState<VersionInfo[] | null>(null);
  const [tab, setTab] = useState<'files' | 'history'>('files');
  const [selected, setSelected] = useState('latest');
  const [files, setFiles] = useState<VersionFile[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [opened, setOpened] = useState<VersionFile | null>(null);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [carryOver, setCarryOver] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = () => setRevision((value) => value + 1);
  useEffect(() => {
    let active = true;
    api<VersionInfo[]>(`${scope}/versions`)
      .then((rows) => {
        if (active) setVersions(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [scope, revision]);
  const published = (versions || []).filter((row) => row.status === 'published');
  const draft = versions?.find((row) => row.status === 'draft') || null;
  const current =
    selected === 'draft'
      ? draft
      : selected === 'latest'
        ? published[0] || null
        : published.find((row) => String(row.number) === selected) || null;
  const ref = current ? (current.status === 'draft' ? 'draft' : String(current.number)) : null;
  const filesUrl = (offset: number) =>
    `${scope}/versions/${ref}/files?limit=${FILES_PAGE}&offset=${offset}&q=${encodeURIComponent(query)}`;
  useEffect(() => {
    if (!ref) {
      setFiles([]);
      setTotal(0);
      return;
    }
    let active = true;
    const timer = setTimeout(() => {
      apiPage<VersionFile>(filesUrl(0))
        .then((page) => {
          if (active) {
            setFiles(page.items);
            setTotal(page.total);
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [scope, ref, query, revision]);
  useEffect(() => {
    if (!opened) return;
    let active = true;
    setPreview(null);
    api<PreviewData>(`${fileBase}/files/${opened.id}/preview`)
      .then((data) => {
        if (active) setPreview(data);
      })
      .catch((e) => {
        if (active) setPreview({ format: 'download', message: e.message });
      });
    return () => {
      active = false;
    };
  }, [fileBase, opened]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="versioned-files" aria-label={`${label} files and versions`}>
      <div className="version-toolbar">
        <div className="version-tabs" role="group" aria-label="Files or version history">
          <button type="button" aria-pressed={tab === 'files'} onClick={() => setTab('files')}>
            <FileText size={15} /> Files
          </button>
          <button type="button" aria-pressed={tab === 'history'} onClick={() => setTab('history')}>
            <History size={15} /> Version history ({published.length})
          </button>
        </div>
        {manage && versions && !draft && (
          <div className="button-row">
            {published.length > 0 && (
              <label className="admin-check">
                <input
                  type="checkbox"
                  checked={carryOver}
                  onChange={(event) => setCarryOver(event.target.checked)}
                />
                <span>Start from version {published[0].number}'s files</span>
              </label>
            )}
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await api(`${scope}/versions`, {
                    method: 'POST',
                    body: JSON.stringify({ carry_over: carryOver }),
                  });
                  refresh();
                })
              }
            >
              New version
            </button>
          </div>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {manage && draft && (
        <section className="version-draft" aria-label="Draft version">
          <div className="version-history-heading">
            <h3>New version (draft)</h3>
            <span className="muted">
              {draft.file_count} files · {formatBytes(draft.total_size)} · private until published
            </span>
          </div>
          <ChunkedUploader versionId={draft.id} uploaded={refresh} />
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setTab('files');
              setSelected('draft');
              setOpened(null);
            }}
          >
            Review draft files
          </button>
          <form
            className="metadata-form"
            onSubmit={(event) => {
              event.preventDefault();
              const note = String(new FormData(event.currentTarget).get('note') || '');
              void run(async () => {
                await api(`${scope}/versions/draft/publish`, {
                  method: 'POST',
                  body: JSON.stringify({ note }),
                });
                setSelected('latest');
                refresh();
                changed?.();
              });
            }}
          >
            <label>
              What changed in this version?
              <textarea
                name="note"
                required
                maxLength={5000}
                rows={3}
                placeholder="Added March observations; removed duplicate rows"
              />
            </label>
            <div className="button-row">
              <button className="button" disabled={busy || !draft.file_count}>
                Publish version
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={() => {
                  if (window.confirm('Discard this draft and the files uploaded to it?'))
                    void run(async () => {
                      await api(`${scope}/versions/draft`, { method: 'DELETE' });
                      setSelected('latest');
                      refresh();
                    });
                }}
              >
                Discard draft
              </button>
            </div>
          </form>
        </section>
      )}
      {tab === 'files' ? (
        <>
          <div className="version-picker">
            <label>
              Version
              <select
                value={selected}
                onChange={(event) => {
                  setSelected(event.target.value);
                  setOpened(null);
                }}
              >
                <option value="latest">
                  Latest{published[0] ? ` (version ${published[0].number})` : ''}
                </option>
                {published.map((row) => (
                  <option key={row.id} value={String(row.number)}>
                    Version {row.number}
                  </option>
                ))}
                {manage && draft && <option value="draft">Draft</option>}
              </select>
            </label>
            <label>
              Filter files
              <input
                type="search"
                value={query}
                maxLength={240}
                placeholder="Path contains…"
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            {current && (
              <p className="muted">
                {current.status === 'draft' ? 'Draft' : `Version ${current.number}`} ·{' '}
                {current.file_count} files · {formatBytes(current.total_size)}
                {current.note ? ` · ${current.note}` : ''}
              </p>
            )}
          </div>
          {!current ? (
            <p>
              {!versions
                ? 'Loading versions…'
                : manage
                  ? 'No published version yet. Start a new version and upload files.'
                  : 'No published version yet.'}
            </p>
          ) : (
            <div className="table-scroll">
              <table className="file-table">
                <thead>
                  <tr>
                    <th scope="col">File</th>
                    <th scope="col">Type</th>
                    <th scope="col">Size</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((file) => (
                    <tr key={file.id} aria-selected={opened?.id === file.id}>
                      <td>
                        <button className="text-button" onClick={() => setOpened(file)}>
                          {file.path}
                        </button>
                      </td>
                      <td>{typeLabels[file.type] || file.type}</td>
                      <td>{formatBytes(file.size)}</td>
                      <td className="file-actions">
                        {current.status === 'draft' && manage && (
                          <button
                            className="icon-button"
                            aria-label={`Remove ${file.path} from the draft`}
                            disabled={busy}
                            onClick={() =>
                              void run(async () => {
                                await api(`${scope}/versions/draft/files/${file.id}`, {
                                  method: 'DELETE',
                                });
                                if (opened?.id === file.id) setOpened(null);
                                refresh();
                              })
                            }
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                        <a
                          className="icon-button"
                          href={`/api${fileBase}/files/${file.id}/download`}
                          aria-label={`Download ${file.path}`}
                        >
                          <Download size={16} />
                        </a>
                      </td>
                    </tr>
                  ))}
                  {!files.length && (
                    <tr>
                      <td colSpan={4}>{query ? 'No matching files.' : 'No files yet.'}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          {files.length < total && (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const page = await apiPage<VersionFile>(filesUrl(files.length));
                  setFiles((old) => [...old, ...page.items]);
                  setTotal(page.total);
                })
              }
            >
              Load more files ({files.length} of {total})
            </button>
          )}
          {opened && (
            <aside className="file-preview" aria-label={`Preview of ${opened.path}`}>
              <header>
                <div>
                  <strong>{opened.path}</strong>
                  <div className="muted">
                    {formatBytes(opened.size)}
                    {opened.sha256 && (
                      <>
                        {' '}
                        · SHA-256 <code title={opened.sha256}>{opened.sha256.slice(0, 12)}…</code>
                      </>
                    )}
                  </div>
                </div>
                <div className="button-row">
                  <a
                    className="button secondary small"
                    href={`/api${fileBase}/files/${opened.id}/download`}
                  >
                    <Download size={15} /> Download
                  </a>
                  <button className="text-button" onClick={() => setOpened(null)}>
                    Close preview
                  </button>
                </div>
              </header>
              {preview ? <FilePreview data={preview} /> : <p role="status">Loading preview…</p>}
            </aside>
          )}
        </>
      ) : (
        <ol className="version-history">
          {published.map((row, index) => (
            <li key={row.id}>
              <div className="version-history-heading">
                <strong>Version {row.number}</strong>
                {index === 0 && <span className="admin-badge">Latest</span>}
                <span className="muted">
                  {row.creator || 'Unknown'} · {when(row.published_at || row.created_at)}
                </span>
              </div>
              <p>{row.note || 'No version notes.'}</p>
              <small className="muted">
                {row.file_count} files · {formatBytes(row.total_size)}
              </small>
              <div className="button-row">
                <button
                  className="text-button"
                  onClick={() => {
                    setSelected(String(row.number));
                    setTab('files');
                    setOpened(null);
                  }}
                >
                  Browse files
                </button>
                {manage && (label !== 'dataset' || published.length > 1) && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete version ${row.number}? Its files are removed, notebooks pinned to it stop working, and the number is never reused.`,
                        )
                      )
                        void run(async () => {
                          await api(`${scope}/versions/${row.number}`, { method: 'DELETE' });
                          setSelected('latest');
                          refresh();
                          changed?.();
                        });
                    }}
                  >
                    Delete version
                  </button>
                )}
              </div>
            </li>
          ))}
          {!published.length && <li className="muted">No published versions yet.</li>}
        </ol>
      )}
    </section>
  );
}
