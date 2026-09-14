import { useEffect, useRef, useState } from 'react';
import { Pause, Play, RotateCcw, UploadCloud, X } from 'lucide-react';
import { formatBytes } from './api';
import { cancelUpload, uploadFile } from './chunkedUpload';
import StorageMeter from './StorageMeter';
import './versions.css';

type Status = 'queued' | 'uploading' | 'paused' | 'assembling' | 'completed' | 'failed';
type Row = { id: string; file: File; path: string; sent: number; status: Status; error: string };
const PARALLEL = 2;
const labels: Record<Status, string> = {
  queued: 'Waiting',
  uploading: 'Uploading',
  paused: 'Paused',
  assembling: 'Verifying',
  completed: 'Uploaded',
  failed: 'Failed',
};

/** Multi-file chunked uploads into a draft version, with pause, retry and resume. */
export default function ChunkedUploader({
  versionId,
  uploaded,
}: {
  versionId: number;
  uploaded: () => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [folder, setFolder] = useState('');
  const [dragging, setDragging] = useState(false);
  const [revision, setRevision] = useState(0);
  const controllers = useRef(new Map<string, AbortController>());
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const running = controllers.current;
    return () => running.forEach((controller) => controller.abort());
  }, []);
  const patch = (id: string, change: Partial<Row>) =>
    setRows((old) => old.map((row) => (row.id === id ? { ...row, ...change } : row)));
  useEffect(() => {
    const active = rows.filter((row) => controllers.current.has(row.id)).length;
    rows
      .filter((row) => row.status === 'queued' && !controllers.current.has(row.id))
      .slice(0, Math.max(0, PARALLEL - active))
      .forEach((row) => void start(row));
  }, [rows]);
  async function start(row: Row) {
    const controller = new AbortController();
    controllers.current.set(row.id, controller);
    patch(row.id, { status: 'uploading', error: '' });
    try {
      await uploadFile(row.file, versionId, row.path, {
        signal: controller.signal,
        onProgress: (sent) => patch(row.id, { sent }),
        onAssembling: () => patch(row.id, { status: 'assembling' }),
      });
      patch(row.id, { status: 'completed', sent: row.file.size });
      setRevision((value) => value + 1);
      uploaded();
    } catch (error) {
      const stopped = (error as Error).name === 'AbortError';
      patch(row.id, {
        status: stopped ? 'paused' : 'failed',
        error: stopped ? '' : (error as Error).message,
      });
    } finally {
      controllers.current.delete(row.id);
      // Wake the queue for the next waiting file.
      setRows((old) => [...old]);
    }
  }
  function add(files: File[]) {
    const base = folder.trim().replace(/^\/+|\/+$/g, '');
    setRows((old) => [
      ...old,
      ...files.map((file) => {
        const relative = file.webkitRelativePath || file.name;
        return {
          id: crypto.randomUUID(),
          file,
          path: base ? `${base}/${relative}` : relative,
          sent: 0,
          status: 'queued' as const,
          error: '',
        };
      }),
    ]);
  }
  async function remove(row: Row) {
    controllers.current.get(row.id)?.abort();
    setRows((old) => old.filter((item) => item.id !== row.id));
    if (row.status !== 'completed') await cancelUpload(row.file, versionId, row.path);
  }
  return (
    <section className="chunked-uploader" aria-label="Upload files">
      <StorageMeter revision={revision} compact />
      <div
        className={`upload-drop ${dragging ? 'dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          add(Array.from(event.dataTransfer.files));
        }}
      >
        <UploadCloud size={32} strokeWidth={1.3} />
        <strong>Drag files here</strong>
        <span>Any file type. Files upload in resumable 8 MB chunks.</span>
        <label className="button secondary upload-browse">
          Choose files
          <input
            ref={input}
            type="file"
            multiple
            aria-label="Choose files to upload"
            onChange={(event) => {
              add(Array.from(event.currentTarget.files || []));
              event.currentTarget.value = '';
            }}
          />
        </label>
      </div>
      <label>
        Folder inside the version (optional)
        <input
          value={folder}
          maxLength={200}
          placeholder="images/train"
          onChange={(event) => setFolder(event.target.value)}
        />
      </label>
      <p className="muted">
        A file with the same path replaces the draft's copy. If a reload interrupts an upload,
        choose the same file again to continue where it stopped.
      </p>
      {rows.length > 0 && (
        <ul className="upload-rows">
          {rows.map((row) => {
            const percent = row.file.size ? Math.floor((row.sent / row.file.size) * 100) : 100;
            return (
              <li key={row.id}>
                <div className="upload-row-heading">
                  <strong title={row.path}>{row.path}</strong>
                  <span>{formatBytes(row.file.size)}</span>
                </div>
                <div
                  className="gpu-meter-track"
                  role="progressbar"
                  aria-label={`Upload progress for ${row.path}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={percent}
                >
                  <div
                    className={row.status === 'failed' ? 'high' : undefined}
                    style={{ width: `${percent}%` }}
                  />
                </div>
                <div className="upload-row-status">
                  <span role="status">
                    {labels[row.status]}
                    {row.status === 'uploading' ? ` · ${percent}%` : ''}
                  </span>
                  <div>
                    {row.status === 'uploading' && (
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => controllers.current.get(row.id)?.abort()}
                      >
                        <Pause size={14} /> Pause
                      </button>
                    )}
                    {(row.status === 'paused' || row.status === 'failed') && (
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => patch(row.id, { status: 'queued', error: '' })}
                      >
                        {row.status === 'paused' ? <Play size={14} /> : <RotateCcw size={14} />}{' '}
                        {row.status === 'paused' ? 'Resume' : 'Retry'}
                      </button>
                    )}
                    {row.status !== 'assembling' && (
                      <button
                        type="button"
                        className="text-button"
                        aria-label={`${row.status === 'completed' ? 'Dismiss' : 'Cancel'} ${row.path}`}
                        onClick={() => void remove(row)}
                      >
                        <X size={14} /> {row.status === 'completed' ? 'Dismiss' : 'Cancel'}
                      </button>
                    )}
                  </div>
                </div>
                {row.error && (
                  <p className="error" role="alert">
                    {row.error}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
