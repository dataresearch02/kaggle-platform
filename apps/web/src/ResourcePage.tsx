import { useEffect, useState } from 'react';
import { ArrowLeft, Copy, Plus, Download } from 'lucide-react';
import { api, formatBytes, FRAMEWORKS, type Item, type ModelVariation, type User } from './api';
import Markdown from './Markdown';
import ModerationActions, { HiddenNotice } from './Moderation';
import DatasetMetadata from './DatasetMetadata';
import ProfilePhoto from './ProfilePhoto';
import NewNotebook from './NewNotebook';
import DiscussionList from './DiscussionList';
import { VoteButton } from './Community';
import VersionedFiles from './VersionedFiles';

export default function ResourcePage({
  kind,
  id,
  user,
  signIn,
  yourWork,
}: {
  kind: 'datasets' | 'models';
  id: number;
  user: User | null;
  signIn: () => void;
  yourWork: () => void;
}) {
  const [item, setItem] = useState<Item | null>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState<{ variationId?: number } | null>(null);
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    if (!revision) setItem(null);
    setError('');
    api<Item>(`/${kind}/${id}`)
      .then((row) => {
        if (active) setItem(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [kind, id, user?.id, revision]);
  const reload = () => setRevision((value) => value + 1);
  const manage = !!user && !!item && (user.id === item.owner_id || user.role === 'admin');
  return (
    <section className="resource-page">
      <a className="discussion-back" href={`#${kind}`}>
        <ArrowLeft size={18} /> All {kind}
      </a>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!item && !error && <p role="status">Loading {kind === 'datasets' ? 'dataset' : 'model'}…</p>}
      {item && (
        <>
          <header className="resource-page-heading">
            <div>
              <small>
                {kind === 'datasets' ? 'Dataset' : 'Model'} ·{' '}
                {item.license || 'License unspecified'}
              </small>
              <h1>{item.title}</h1>
              <div className="resource-page-author">
                <ProfilePhoto
                  src={
                    item.owner
                      ? `/api/profiles/${encodeURIComponent(item.owner)}/avatar`
                      : undefined
                  }
                  alt="Creator profile photo"
                />
                <span>{item.owner}</span>
              </div>
            </div>
            <div className="button-row">
              <VoteButton
                kind={kind === 'datasets' ? 'dataset' : 'model'}
                id={id}
                votes={item.votes}
                voted={item.voted}
                ownerId={item.owner_id}
                user={user}
                signIn={signIn}
                label={item.title}
              />
              <button className="button secondary" onClick={yourWork}>
                Your Work
              </button>
              <button
                className="button"
                disabled={item.input_available === false}
                onClick={() => (user ? setCreating({}) : signIn())}
              >
                <Plus size={18} /> New notebook
              </button>
            </div>
          </header>
          <HiddenNotice hidden={item.hidden} reason={item.hidden_reason} />
          <ModerationActions
            kind={kind === 'datasets' ? 'dataset' : 'model'}
            id={id}
            ownerId={item.owner_id}
            hidden={item.hidden}
            user={user}
            signIn={signIn}
            label={kind === 'datasets' ? 'dataset' : 'model'}
            onChange={(change) => {
              if (change.deleted) location.hash = kind;
              else setItem({ ...item, hidden: change.hidden, hidden_reason: change.reason });
            }}
          />
          {item.input_available === false && (
            <p>
              {kind === 'datasets'
                ? 'Publish a version with files to attach this dataset to a notebook.'
                : 'Publish a version with files in a variation to attach this model to a notebook.'}
            </p>
          )}
          {notice && <p role="status">{notice}</p>}
          {kind === 'datasets' ? (
            <>
              <Markdown>{item.description || ''}</Markdown>
              <div className="pill-row">
                {item.latest_version ? (
                  <>
                    <span>Version {item.latest_version.number}</span>
                    <span>{item.latest_version.file_count} files</span>
                    <span>{formatBytes(item.latest_version.total_size)}</span>
                  </>
                ) : (
                  <span>No published version yet</span>
                )}
              </div>
              {item.filename && (
                <a className="button secondary" href={`/api/datasets/${id}/download`}>
                  <Download size={17} /> Download {item.filename}
                </a>
              )}
              <VersionedFiles
                scope={`/datasets/${id}`}
                fileBase={`/datasets/${id}`}
                manage={manage}
                label="dataset"
                changed={reload}
              />
              <DatasetMetadata key={revision} id={id} owner={manage} />
            </>
          ) : (
            <>
              <div className="pill-row">
                <span>{item.framework}</span>
                <span>{item.license}</span>
              </div>
              <ModelCard
                item={item}
                manage={manage}
                saved={(card) => setItem((current) => (current ? { ...current, card } : current))}
              />
              <ModelVariations
                model={item}
                manage={manage}
                reload={reload}
                newNotebook={(variationId) => (user ? setCreating({ variationId }) : signIn())}
              />
              {item.url && (
                <p className="external-reference">
                  External reference (not available offline):{' '}
                  <a href={item.url} target="_blank" rel="noreferrer noopener">
                    {item.url}
                  </a>
                </p>
              )}
            </>
          )}
          <section className="resource-discussion" aria-label="Discussion">
            <DiscussionList
              scope={kind === 'datasets' ? 'dataset' : 'model'}
              scopeId={id}
              scopeTitle={item.title}
              heading="Discussion"
              pageSize={10}
              user={user}
              signIn={signIn}
            />
          </section>
        </>
      )}
      {creating && (
        <NewNotebook
          inputSource={{
            kind: kind === 'datasets' ? 'dataset' : 'model',
            id,
            variationId: creating.variationId,
          }}
          close={() => setCreating(null)}
          saved={() => setNotice('Notebook saved to Your Work.')}
        />
      )}
    </section>
  );
}

/** The Markdown model card, rendered with the sanitized Markdown component. */
function ModelCard({
  item,
  manage,
  saved,
}: {
  item: Item;
  manage: boolean;
  saved: (card: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.card || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <section aria-label="Model card">
      <div className="metadata-heading">
        <h2>Model card</h2>
        {manage && (
          <button
            className="button secondary"
            onClick={() => {
              setText(item.card || '');
              setEditing(!editing);
            }}
          >
            {editing ? 'Cancel card edit' : 'Edit model card'}
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {editing ? (
        <form
          className="metadata-form model-card-editor"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError('');
            try {
              const result = await api<{ card: string }>(`/models/${item.id}/card`, {
                method: 'PUT',
                body: JSON.stringify({ card: text }),
              });
              saved(result.card);
              setEditing(false);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Markdown
            <textarea
              value={text}
              maxLength={100000}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <button className="button" disabled={busy}>
            Save model card
          </button>
        </form>
      ) : (
        <article className="model-card">
          <Markdown>{item.card || item.description || ''}</Markdown>
        </article>
      )}
    </section>
  );
}

function ModelVariations({
  model,
  manage,
  reload,
  newNotebook,
}: {
  model: Item;
  manage: boolean;
  reload: () => void;
  newNotebook: (variationId: number) => void;
}) {
  const variations: ModelVariation[] = model.variations || [];
  const [selected, setSelected] = useState<number | null>(
    () => variations.find((row) => row.latest_version)?.id ?? variations[0]?.id ?? null,
  );
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const current = variations.find((row) => row.id === selected) || variations[0];
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
    <section className="model-variations" aria-label="Model variations">
      <div className="metadata-heading">
        <h2>Variations</h2>
        {manage && (
          <button className="button secondary" onClick={() => setAdding(!adding)}>
            {adding ? 'Cancel' : 'Add variation'}
          </button>
        )}
      </div>
      <p className="muted">
        Each framework and variation, such as PyTorch "base" or "small", has its own numbered
        versions.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {adding && (
        <form
          className="metadata-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void run(async () => {
              const row = await api<ModelVariation>(`/models/${model.id}/variations`, {
                method: 'POST',
                body: JSON.stringify({
                  framework: form.get('framework'),
                  slug: String(form.get('slug') || '').trim(),
                  description: form.get('description') || '',
                }),
              });
              setSelected(row.id);
              setAdding(false);
              reload();
            });
          }}
        >
          <label>
            Framework
            <select name="framework" defaultValue="pytorch">
              {FRAMEWORKS.map((framework) => (
                <option key={framework.value} value={framework.value}>
                  {framework.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Variation
            <input
              name="slug"
              required
              maxLength={40}
              pattern="[a-z0-9]([a-z0-9\-]{0,38}[a-z0-9])?"
              placeholder="base"
              title="Lowercase letters, numbers and hyphens"
            />
          </label>
          <label>
            Description (optional)
            <input name="description" maxLength={2000} />
          </label>
          <button className="button" disabled={busy}>
            Create variation
          </button>
        </form>
      )}
      <div className="variation-list" role="tablist" aria-label="Variations">
        {variations.map((row) => (
          <button
            key={row.id}
            role="tab"
            aria-selected={row.id === current?.id}
            onClick={() => setSelected(row.id)}
          >
            <strong>{row.framework_label}</strong>
            <span>{row.slug}</span>
            <small>
              {row.latest_version
                ? `Version ${row.latest_version.number} · ${formatBytes(row.latest_version.total_size)}`
                : 'No versions yet'}
            </small>
          </button>
        ))}
      </div>
      {current && (
        <>
          {current.description && <p>{current.description}</p>}
          {current.latest_version && (
            <div className="usage-snippet">
              <div className="metadata-heading">
                <h3>Use in a notebook</h3>
                <div className="button-row">
                  <button
                    className="button secondary small"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(current.snippet);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 2000);
                      } catch {
                        setError('Copying is unavailable here; select the code instead.');
                      }
                    }}
                  >
                    <Copy size={14} /> {copied ? 'Copied' : 'Copy code'}
                  </button>
                  <button className="button small" onClick={() => newNotebook(current.id)}>
                    <Plus size={14} /> New notebook with this variation
                  </button>
                </div>
              </div>
              <p className="muted">
                Attach it with Add Input → Models. Files are copied read-only to{' '}
                <code>{current.input_path}</code> in interactive sessions, Save &amp; Run All and
                scheduled runs.
              </p>
              <pre>
                <code>{current.snippet}</code>
              </pre>
            </div>
          )}
          <VersionedFiles
            key={current.id}
            scope={`/models/${model.id}/variations/${current.id}`}
            fileBase={`/models/${model.id}`}
            manage={manage}
            label="model variation"
            changed={reload}
          />
          {manage && (
            <button
              className="text-button"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete the ${current.framework_label} "${current.slug}" variation and all its versions and files?`,
                  )
                )
                  void run(async () => {
                    await api(`/models/${model.id}/variations/${current.id}`, {
                      method: 'DELETE',
                    });
                    setSelected(null);
                    reload();
                  });
              }}
            >
              Delete this variation
            </button>
          )}
        </>
      )}
    </section>
  );
}
