import { useEffect, useState } from 'react';
import { X, Table2 } from 'lucide-react';
import { api } from './api';
import type { Input, InputFile } from './NotebookPanel';

export type InputSelection = {
  source: Input;
  file: InputFile;
};
type Preview = {
  format: string;
  columns?: string[];
  rows?: string[][];
  text?: string;
  message?: string;
  truncated?: boolean;
};

export default function NotebookInputPreview({
  selection,
  close,
}: {
  selection: InputSelection;
  close: () => void;
}) {
  const [data, setData] = useState<Preview | null>(null);
  const [error, setError] = useState('');
  const { source, file } = selection;
  useEffect(() => {
    let active = true;
    setData(null);
    setError('');
    api<Preview>(
      `/input-sources/${source.kind || 'dataset'}/${source.id}/files/${file.id}/preview?file_kind=${encodeURIComponent(file.kind || '')}`,
    )
      .then((result) => {
        if (active) setData(result);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [source.kind, source.id, file.id, file.kind]);
  return (
    <section className="notebook-input-preview" aria-label="Input data preview">
      <header>
        <div>
          <Table2 size={18} />
          <strong>{file.filename}</strong>
          <span>{source.title}</span>
        </div>
        <button aria-label="Close input data preview" onClick={close}>
          <X size={18} />
        </button>
      </header>
      <p className="notebook-input-preview-path">{file.path}</p>
      <div className="notebook-input-preview-content" tabIndex={0} aria-label="Input file contents">
        {error ? (
          <p role="alert">{error}</p>
        ) : !data ? (
          <p role="status">Loading input data…</p>
        ) : data.format === 'table' ? (
          <table>
            <thead>
              <tr>
                {data.columns?.map((column, i) => (
                  <th key={i} scope="col">
                    {column || `Column ${i + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows?.map((row, i) => (
                <tr key={i}>
                  {data.columns?.map((_, j) => (
                    <td key={j}>{row[j] ?? ''}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : data.format === 'text' ? (
          <pre>{data.text}</pre>
        ) : (
          <p>{data.message}</p>
        )}
      </div>
      {data && (
        <small>
          {data.format === 'table'
            ? `${data.rows?.length || 0} preview rows · up to 50 columns`
            : 'Read-only preview'}
          {data.truncated ? ' · Preview limited; the full file is available to your notebook.' : ''}
        </small>
      )}
    </section>
  );
}
