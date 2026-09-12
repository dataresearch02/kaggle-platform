import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { api } from './api';
import { type Asset, type Collection, modelExample, taskExample } from './benchmarkTypes';

type Kind = 'task' | 'model' | 'collection';
export default function BenchmarkDrawer({
  kind,
  item,
  close,
  saved,
}: {
  kind: Kind;
  item?: Asset | Collection;
  close: () => void;
  saved: (id: number) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const asset = item as Asset | undefined;
  const collection = item as Collection | undefined;
  const [title, setTitle] = useState(item?.title || '');
  const [description, setDescription] = useState(item?.description || '');
  const [visibility, setVisibility] = useState(item?.visibility || 'private');
  const [provider, setProvider] = useState(asset?.provider_id || '');
  const [providers, setProviders] = useState<
    { id: string; label: string; model: string; available: boolean }[]
  >([]);
  useEffect(() => {
    api<typeof providers>('/benchmark-hub/providers')
      .then(setProviders)
      .catch((e) => setError(e.message));
  }, []);
  const [source, setSource] = useState(
    asset?.versions?.[0]?.source || (kind === 'task' ? taskExample : modelExample),
  );
  const [cases, setCases] = useState(
    JSON.stringify(
      asset?.versions?.[0]?.cases || [{ prompt: 'Hello', expected: 'Hello' }],
      null,
      2,
    ),
  );
  const [tasks, setTasks] = useState<number[]>(collection?.tasks || []);
  const [models, setModels] = useState<number[]>(collection?.models || []);
  const [choices, setChoices] = useState<Asset[]>([]);
  const [assetSearch, setAssetSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState<Record<string, number | null>>({});
  useEffect(() => {
    const focus = document.activeElement as HTMLElement;
    dialog.current?.showModal();
    return () => focus?.focus();
  }, []);
  useEffect(() => {
    if (kind !== 'collection') return;
    let active = true;
    const timer = setTimeout(() => {
      Promise.all(
        ['task', 'model'].map(async (kind) => ({
          kind,
          batch: await api<{ items: Asset[]; next_cursor: number | null }>(
            `/benchmark-hub/assets?kind=${kind}&q=${encodeURIComponent(assetSearch)}`,
          ),
        })),
      )
        .then((batches) => {
          if (active) {
            setChoices(batches.flatMap((b) => b.batch.items));
            setNext(Object.fromEntries(batches.map((b) => [b.kind, b.batch.next_cursor])));
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [kind, assetSearch]);
  const selectedAssets = [
    ...(collection?.task_details || []),
    ...(collection?.model_details || []),
  ];
  const options = [
    ...selectedAssets,
    ...choices.filter((a) => !selectedAssets.some((b) => b.version_id === a.version_id)),
  ];
  return createPortal(
    <dialog
      ref={dialog}
      className="discussion-compose-drawer benchmark-drawer"
      aria-label={`${item ? 'Edit' : 'Create'} ${kind === 'collection' ? 'benchmark' : kind}`}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          setBusy(true);
          setError('');
          try {
            const data = {
              title,
              description,
              visibility,
              ...(kind === 'collection'
                ? { tasks, models }
                : {
                    source,
                    provider_id: provider || null,
                    cases: kind === 'task' ? JSON.parse(cases) : [],
                  }),
            };
            const path =
              kind === 'collection'
                ? `/benchmark-hub/collections${item ? `/${item.id}` : ''}`
                : `/benchmark-hub/assets/${item ? item.id : kind}`;
            const row = await api<{ id: number }>(path, {
              method: item ? 'PUT' : 'POST',
              body: JSON.stringify(data),
            });
            saved(row.id);
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <header>
          <h2>
            {item ? 'Edit' : 'Create'} {kind === 'collection' ? 'benchmark' : kind}
          </h2>
          <button
            type="button"
            disabled={busy}
            onClick={close}
            aria-label="Close benchmark sidebar"
          >
            <X />
          </button>
        </header>
        <div className="discussion-compose-body">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <label>
            Name
            <input
              required
              minLength={3}
              maxLength={160}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            Description
            <textarea
              rows={3}
              maxLength={10000}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label>
            Visibility
            <select
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as 'public' | 'private')}
            >
              <option value="private">Private</option>
              <option value="public">Public</option>
            </select>
          </label>
          {kind === 'collection' ? (
            <>
              <p>
                Select reusable tasks and model versions. Each task contributes equally to the
                overall score.
              </p>
              <label>
                Find tasks or models
                <input value={assetSearch} onChange={(e) => setAssetSearch(e.target.value)} />
              </label>
              {(['task', 'model'] as const).map((k) => (
                <fieldset key={k}>
                  <legend>{k === 'task' ? 'Tasks' : 'Models'}</legend>
                  {options
                    .filter((a) => a.kind === k)
                    .map((a) => {
                      const selected = k === 'task' ? tasks : models;
                      const change = k === 'task' ? setTasks : setModels;
                      return (
                        <label className="benchmark-choice" key={a.version_id}>
                          <input
                            type="checkbox"
                            checked={selected.includes(a.version_id)}
                            onChange={(e) =>
                              change(
                                e.target.checked
                                  ? [
                                      ...selected.filter(
                                        (id) =>
                                          !options.some(
                                            (other) => other.id === a.id && other.version_id === id,
                                          ),
                                      ),
                                      a.version_id,
                                    ]
                                  : selected.filter((id) => id !== a.version_id),
                              )
                            }
                          />
                          {a.title} · version #{a.version_id} · {a.visibility}
                        </label>
                      );
                    })}
                  {!options.some((a) => a.kind === k) && (
                    <p>No {k}s found. Create one first, or save this benchmark and add it later.</p>
                  )}
                  {next[k] && (
                    <button
                      type="button"
                      className="text-button"
                      onClick={async () => {
                        try {
                          const batch = await api<{ items: Asset[]; next_cursor: number | null }>(
                            `/benchmark-hub/assets?kind=${k}&before=${next[k]}&q=${encodeURIComponent(assetSearch)}`,
                          );
                          setChoices((old) => [...old, ...batch.items]);
                          setNext((old) => ({ ...old, [k]: batch.next_cursor }));
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      Load more {k}s
                    </button>
                  )}
                </fieldset>
              ))}
            </>
          ) : (
            <>
              <p>
                {kind === 'task'
                  ? 'Define evaluate(model, case). Use model.prompt(input); return a boolean, score from 0 to 1, or (passed, total).'
                  : 'Define predict(prompt) using Python and the installed CPU libraries. Models run offline with no service credentials.'}
              </p>
              {kind === 'model' && (
                <label>
                  Execution
                  <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                    <option value="">Local Python model (CPU)</option>
                    {providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label} · {p.model}
                        {p.available ? '' : ' · credentials needed'}
                      </option>
                    ))}
                  </select>
                  {!providers.length && (
                    <small>
                      No API providers are configured. An administrator can add compatible model
                      endpoints.
                    </small>
                  )}
                </label>
              )}
              <label>
                Import Python or notebook file
                <input
                  type="file"
                  accept=".py,.ipynb"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    try {
                      if (file.size > 100000) throw Error('Source file must be under 100 KB');
                      const text = await file.text();
                      setSource(
                        file.name.endsWith('.ipynb')
                          ? JSON.parse(text)
                              .cells.filter((c: { cell_type: string }) => c.cell_type === 'code')
                              .map((c: { source: string | string[] }) =>
                                Array.isArray(c.source) ? c.source.join('') : c.source,
                              )
                              .join('\n\n')
                          : text,
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                />
              </label>
              {!provider && (
                <label>
                  Python source
                  <textarea
                    className="benchmark-source"
                    spellCheck={false}
                    rows={14}
                    required
                    maxLength={100000}
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                  />
                </label>
              )}
              {kind === 'task' && (
                <label>
                  Evaluation cases (JSON array)
                  <textarea
                    className="benchmark-source"
                    rows={7}
                    required
                    value={cases}
                    onChange={(e) => setCases(e.target.value)}
                  />
                </label>
              )}
              <p>
                Saving creates an immutable version. Existing benchmarks continue using their
                selected version.
              </p>
            </>
          )}
        </div>
        <footer>
          <button type="button" className="button secondary" disabled={busy} onClick={close}>
            Cancel
          </button>
          <button className="button" disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </footer>
      </form>
    </dialog>,
    document.body,
  );
}
