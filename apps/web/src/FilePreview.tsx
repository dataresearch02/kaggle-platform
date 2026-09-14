import Markdown from './Markdown';
import { formatBytes } from './api';
import './versions.css';

/** Bounded preview JSON from the API; see apps/api/app/file_previews.py. */
export type PreviewData = {
  format: string;
  type?: string;
  size?: number;
  path?: string;
  message?: string;
  truncated?: boolean;
  columns?: string[];
  rows?: string[][];
  summary?: {
    name: string;
    type: string;
    values: number;
    missing: number;
    distinct: number;
    distinct_capped: boolean;
    min: number | null;
    max: number | null;
    mean: number | null;
  }[];
  sampled_rows?: number;
  total_columns?: number;
  text?: string;
  url?: string;
  dtype?: string;
  shape?: number[];
  fortran_order?: boolean;
  values?: (number | boolean | string)[];
  entries?: {
    name: string;
    size: number;
    compressed_size: number;
    directory: boolean;
    unsafe_path: boolean;
  }[];
  total_entries?: number;
  uncompressed_size?: number;
  suspicious?: boolean;
};

const stat = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : Number.isInteger(value)
      ? value.toLocaleString()
      : value.toPrecision(5);

export default function FilePreview({ data }: { data: PreviewData }) {
  const limited = data.truncated ? (
    <small className="muted">
      Preview limited to the start of the file. Download it or read it in a notebook for
      everything.
    </small>
  ) : null;
  if (data.format === 'table')
    return (
      <div className="file-preview-body">
        <div className="table-scroll">
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
        </div>
        {data.summary && (
          <>
            <h4>
              Column summary{' '}
              <small className="muted">
                from {(data.sampled_rows || 0).toLocaleString()} rows
                {data.total_columns && data.columns && data.total_columns > data.columns.length
                  ? ` · first ${data.columns.length} of ${data.total_columns} columns`
                  : ''}
              </small>
            </h4>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Column</th>
                    <th scope="col">Type</th>
                    <th scope="col">Values</th>
                    <th scope="col">Missing</th>
                    <th scope="col">Distinct</th>
                    <th scope="col">Min</th>
                    <th scope="col">Mean</th>
                    <th scope="col">Max</th>
                  </tr>
                </thead>
                <tbody>
                  {data.summary.map((column, i) => (
                    <tr key={i}>
                      <td>{column.name}</td>
                      <td>{column.type}</td>
                      <td>{column.values.toLocaleString()}</td>
                      <td>{column.missing.toLocaleString()}</td>
                      <td>
                        {column.distinct.toLocaleString()}
                        {column.distinct_capped ? '+' : ''}
                      </td>
                      <td>{stat(column.min)}</td>
                      <td>{stat(column.mean)}</td>
                      <td>{stat(column.max)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {limited}
      </div>
    );
  if (data.format === 'text' || data.format === 'json')
    return (
      <div className="file-preview-body">
        <pre className="file-preview-text">{data.text}</pre>
        {limited}
      </div>
    );
  if (data.format === 'markdown')
    return (
      <div className="file-preview-body">
        <div className="file-preview-markdown">
          <Markdown>{data.text || ''}</Markdown>
        </div>
        {limited}
      </div>
    );
  if (data.format === 'image' && data.url)
    return (
      <img
        className="file-preview-image"
        src={data.url}
        alt={`Preview of ${data.path || 'image'}`}
        loading="lazy"
      />
    );
  if (data.format === 'array')
    return (
      <div className="file-preview-body">
        <p>
          NumPy array · dtype <code>{data.dtype}</code> · shape{' '}
          <code>
            ({data.shape?.join(', ')}
            {data.shape?.length === 1 ? ',' : ''})
          </code>
          {data.fortran_order ? ' · Fortran order' : ''}
        </p>
        {data.values?.length ? (
          <pre className="file-preview-text">
            {data.values.join(', ')}
            {data.truncated ? ', …' : ''}
          </pre>
        ) : (
          <p className="muted">Values are not previewed for this data type.</p>
        )}
      </div>
    );
  if (data.format === 'archive')
    return (
      <div className="file-preview-body">
        {data.message && <p>{data.message}</p>}
        {data.suspicious && (
          <p className="file-preview-warning" role="note">
            This archive expands to {formatBytes(data.uncompressed_size || 0)}, far more than its
            size. Arena never extracts archives; be careful extracting it yourself.
          </p>
        )}
        {data.entries?.some((entry) => entry.unsafe_path) && (
          <p className="file-preview-warning" role="note">
            Some member paths point outside the archive folder. Do not extract it with tools
            that follow them.
          </p>
        )}
        {!!data.entries?.length && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Member</th>
                  <th scope="col">Size</th>
                  <th scope="col">Compressed</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry, i) => (
                  <tr key={i}>
                    <td>
                      {entry.name}
                      {entry.unsafe_path ? ' (unsafe path)' : ''}
                    </td>
                    <td>{entry.directory ? 'Folder' : formatBytes(entry.size)}</td>
                    <td>{entry.directory ? '' : formatBytes(entry.compressed_size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data.total_entries !== undefined && (
          <small className="muted">
            {data.total_entries.toLocaleString()} members
            {data.uncompressed_size !== undefined
              ? ` · ${formatBytes(data.uncompressed_size)} uncompressed`
              : ''}
            {data.truncated ? ' · listing limited' : ''}
          </small>
        )}
      </div>
    );
  return <p>{data.message || 'Preview is not available for this file. Download it to use it.'}</p>;
}
