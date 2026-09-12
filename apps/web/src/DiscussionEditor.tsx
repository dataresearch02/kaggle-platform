import { useRef, useState } from 'react';
import { Bold, Italic, Heading2, List, Link, Table2, ImagePlus, Code2, Quote } from 'lucide-react';
import Markdown from './Markdown';
import { api } from './api';

export default function DiscussionEditor({
  value,
  onChange,
  competitionId,
  label,
  disabled = false,
  limit = 20000,
  onUploadingChange,
}: {
  value: string;
  onChange: (value: string) => void;
  competitionId: number;
  label: string;
  disabled?: boolean;
  limit?: number;
  onUploadingChange?: (busy: boolean) => void;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const image = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  function insert(before: string, after = '', placeholder = '') {
    const start = input.current?.selectionStart ?? value.length;
    const end = input.current?.selectionEnd ?? value.length;
    const text = value.slice(start, end) || placeholder;
    const updated = value.slice(0, start) + before + text + after + value.slice(end);
    if (updated.length > limit) {
      setError(`Keep the message under ${limit.toLocaleString()} characters.`);
      return;
    }
    onChange(updated);
    setPreview(false);
    requestAnimationFrame(() => {
      input.current?.focus();
      input.current?.setSelectionRange(start + before.length, start + before.length + text.length);
    });
  }
  const tools = [
    { name: 'Bold', Icon: Bold, run: () => insert('**', '**', 'bold text') },
    { name: 'Italic', Icon: Italic, run: () => insert('*', '*', 'italic text') },
    { name: 'Heading', Icon: Heading2, run: () => insert('\n## ', '\n', 'Heading') },
    { name: 'List', Icon: List, run: () => insert('\n- ', '\n', 'List item') },
    { name: 'Quote', Icon: Quote, run: () => insert('\n> ', '\n', 'Quote') },
    {
      name: 'Code block',
      Icon: Code2,
      run: () => insert('\n```python\n', '\n```\n', 'print("Hello")'),
    },
    {
      name: 'Insert link',
      Icon: Link,
      run: () => insert('[', '](https://example.com)', 'link text'),
    },
    {
      name: 'Insert table',
      Icon: Table2,
      run: () => insert('\n| Column 1 | Column 2 |\n| --- | --- |\n| Value | Value |\n'),
    },
  ];
  return (
    <div className="discussion-editor">
      <div className="discussion-editor-tabs">
        <button type="button" aria-pressed={!preview} onClick={() => setPreview(false)}>
          Write
        </button>
        <button type="button" aria-pressed={preview} onClick={() => setPreview(true)}>
          Preview
        </button>
      </div>
      {!preview && (
        <div className="discussion-format-tools" role="toolbar" aria-label={`${label} formatting`}>
          {tools.map(({ name, Icon, run }) => (
            <button
              type="button"
              key={name}
              title={name}
              aria-label={name}
              disabled={disabled || uploading}
              onClick={run}
            >
              <Icon size={18} />
            </button>
          ))}
          <button
            type="button"
            aria-label="Upload image"
            title="Upload image"
            disabled={disabled || uploading}
            onClick={() => image.current?.click()}
          >
            <ImagePlus size={18} />
          </button>
        </div>
      )}
      <input
        ref={image}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp"
        hidden
        aria-label={`${label} image`}
        onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (!file) return;
          if (file.size > 5 * 1024 * 1024) {
            setError('Images must be 5 MB or smaller.');
            return;
          }
          setUploading(true);
          onUploadingChange?.(true);
          setError('');
          try {
            const form = new FormData();
            form.append('file', file);
            const result = await api<{ url: string }>(
              `/competition-discussions/images?competition_id=${competitionId}`,
              { method: 'POST', body: form },
            );
            insert(`\n![Image](${result.url})\n`);
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setUploading(false);
            onUploadingChange?.(false);
          }
        }}
      />
      {preview ? (
        <div className="discussion-editor-preview">
          <Markdown>{value || '*Nothing to preview yet.*'}</Markdown>
        </div>
      ) : (
        <textarea
          ref={input}
          aria-label={label}
          value={value}
          maxLength={limit}
          disabled={disabled || uploading}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Share your thoughts. Use the toolbar or Markdown to format your message."
          rows={9}
        />
      )}
      <div className="discussion-editor-hint">
        {uploading ? 'Uploading image…' : 'Markdown supported · Images up to 5 MB'}
        <span>
          {value.length.toLocaleString()} / {limit.toLocaleString()}
        </span>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
