import { useRef, useState } from 'react';
import { Check, FileSpreadsheet, UploadCloud, X } from 'lucide-react';

export default function FileUpload({
  name,
  label,
  maxMB,
  hint,
}: {
  name: string;
  label: string;
  maxMB: number;
  hint: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  function select(files: FileList | null) {
    const next = files?.[0];
    const problem = !next
      ? ''
      : files!.length > 1
        ? 'Choose one CSV file.'
        : !next.name.toLowerCase().endsWith('.csv')
          ? 'Choose a CSV file.'
          : !next.size
            ? 'This file is empty.'
            : next.size > maxMB * 1024 * 1024
              ? `File must be ${maxMB} MB or smaller.`
              : '';
    setError(problem);
    setFile(problem ? null : next || null);
    if (problem && input.current) input.current.value = '';
  }
  return (
    <section className="upload-section">
      <h2>{label}</h2>
      <p>{hint}</p>
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
          if (input.current?.disabled || input.current?.matches(':disabled')) return;
          if (input.current) {
            input.current.files = event.dataTransfer.files;
            select(event.dataTransfer.files);
          }
        }}
      >
        <UploadCloud size={38} strokeWidth={1.3} />
        <strong>Drag and drop your CSV here</strong>
        <span>or choose a file from your computer</span>
        <label className="button secondary upload-browse">
          Browse files
          <input
            ref={input}
            aria-label={label}
            aria-describedby={`${name}-hint`}
            name={name}
            type="file"
            accept=".csv,text/csv"
            required
            onChange={(event) => select(event.currentTarget.files)}
          />
        </label>
        <small id={`${name}-hint`}>CSV · up to {maxMB} MB · one file</small>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {file && (
        <div className="upload-file">
          <FileSpreadsheet size={24} />
          <span>
            <strong>{file.name}</strong>
            <small>
              {file.size < 1024 ? `${file.size} bytes` : `${(file.size / 1024).toFixed(1)} KB`} ·
              Ready to upload
            </small>
          </span>
          <Check size={18} />
          <button
            type="button"
            className="icon-button"
            aria-label={`Remove ${label}`}
            onClick={() => {
              input.current!.value = '';
              setFile(null);
              setError('');
            }}
          >
            <X size={18} />
          </button>
        </div>
      )}
    </section>
  );
}
