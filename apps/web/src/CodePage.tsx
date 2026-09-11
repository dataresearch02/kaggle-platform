import CodeComments from './CodeComments';
import { useEffect, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import Markdown from './Markdown';
import { ArrowLeft, GitFork, Bookmark, Database, FileOutput, Code2 } from 'lucide-react';
import { api, type User } from './api';
import NotebookWorkspace, { CellOutput, text, type Document } from './NotebookWorkspace';

const viewTabs = ['Notebook', 'Input', 'Output', 'Logs', 'Comments'] as const;
type ViewTab = (typeof viewTabs)[number];

type CodeDetail = {
  id: number;
  title: string;
  description: string;
  owner: string;
  owner_id: number;
  working_competition_id?: number | null;
  private?: boolean;
  document: Document;
  inputs: { id: number; title: string; filename: string; available: boolean }[];
  published_at: string | null;
  forked_from: number | null;
  bookmarked: boolean;
  competitions: { id: number; title: string }[];
};
export default function CodePage({
  id,
  edit,
  competitionId,
  user,
  signIn,
  changed,
}: {
  id: number;
  edit: boolean;
  competitionId?: number;
  user: User | null;
  signIn: () => void;
  changed: () => void;
}) {
  const [tab, setTab] = useState<ViewTab>('Notebook');
  useEffect(() => setTab('Notebook'), [id]);
  const publishedCells = useRef<HTMLElement>(null);
  const [headings, setHeadings] = useState<{ id: string; title: string; level: number }[]>([]);
  const [data, setData] = useState<CodeDetail | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [shares, setShares] = useState<{ id: number; username: string }[]>([]);
  const [username, setUsername] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let alive = true;
    setData(null);
    setError('');
    api<CodeDetail>(`/code/${id}`)
      .then((row) => {
        if (alive) setData(row);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [id, edit, user?.id]);
  useEffect(() => {
    if (!sharing) return;
    let alive = true;
    api<{ id: number; username: string }[]>(`/code/${id}/shares`)
      .then((rows) => {
        if (alive) setShares(rows);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [id, sharing, notice]);
  useEffect(() => {
    const nodes = publishedCells.current?.querySelectorAll<HTMLElement>(
      '.notebook-markdown h1, .notebook-markdown h2, .notebook-markdown h3, .notebook-markdown h4, .notebook-markdown h5, .notebook-markdown h6',
    );
    setHeadings(
      Array.from(nodes || []).map((node, index) => {
        node.id = `published-${id}-heading-${index}`;
        node.tabIndex = -1;
        return {
          id: node.id,
          title: node.textContent || 'Untitled heading',
          level: Number(node.tagName.slice(1)),
        };
      }),
    );
  }, [data, edit]);
  useEffect(() => {
    if (!edit || !data || user?.id !== data.owner_id) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [edit, data, user?.id]);
  if (!data)
    return (
      <section>
        <a href="#notebooks">Back to codes</a>
        <p role={error ? 'alert' : 'status'}>{error || 'Loading published code…'}</p>
      </section>
    );
  const owner = !!user && user.id === data.owner_id;
  competitionId = competitionId || data.working_competition_id || undefined;
  const context = competitionId ? `?competition=${competitionId}` : '';
  if (edit)
    return owner ? (
      <div className="code-editor-fullscreen">
        <NotebookWorkspace
          key={`${id}-${user.id}`}
          notebookId={id}
          title={data.title}
          initialCode={data.document.cells
            .filter((cell) => cell.cell_type === 'code')
            .map((cell) => text(cell.source))
            .join('\n\n')}
          signedIn
          signIn={signIn}
          autoStart
          canPublish
          competitionId={competitionId}
          onClose={() => {
            location.hash = competitionId ? `competitions/${competitionId}/code` : 'notebooks';
            changed();
          }}
        />
      </div>
    ) : (
      <section className="empty">
        <h2>This editor belongs to the author</h2>
        <p>Fork the published code to make your own changes.</p>
        <a className="button" href={`#code/${id}${context}`}>
          View code
        </a>
      </section>
    );
  const outputs = data.document.cells.reduce(
    (count, cell) => count + (cell.outputs?.length || 0),
    0,
  );
  return (
    <article className="code-view-page">
      <a
        className="text-button"
        href={competitionId ? `#competitions/${competitionId}/code` : '#notebooks'}
      >
        <ArrowLeft size={16} />
        {competitionId ? 'Back to competition code' : 'All codes'}
      </a>
      <header className="code-view-header">
        <div>
          <div className="eyebrow">
            {data.private ? 'Private notebook' : 'Published notebook'} · read only
          </div>
          <h1>{data.title}</h1>
          <p>
            By {data.owner}
            {data.published_at
              ? ` · Published ${new Date(data.published_at).toLocaleString()}`
              : ' · Source preview'}
          </p>
          {data.forked_from && (
            <p>
              Forked from <a href={`#code/${data.forked_from}`}>notebook #{data.forked_from}</a>
            </p>
          )}
        </div>
        <div className="button-row">
          <button
            className="button secondary"
            aria-pressed={data.bookmarked}
            disabled={busy}
            onClick={async () => {
              if (!user) {
                signIn();
                return;
              }
              setBusy(true);
              setError('');
              try {
                const result = await api<{ bookmarked: boolean }>(`/code/${id}/bookmark`, {
                  method: data.bookmarked ? 'DELETE' : 'PUT',
                });
                setData({ ...data, ...result });
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Bookmark size={17} fill={data.bookmarked ? 'currentColor' : 'none'} />
            {data.bookmarked ? 'Bookmarked' : 'Bookmark'}
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={async () => {
              if (!user) {
                signIn();
                return;
              }
              setBusy(true);
              setError('');
              try {
                const fork = await api<{ id: number }>(
                  `/code/${id}/fork${competitionId ? `?competition_id=${competitionId}` : ''}`,
                  { method: 'POST' },
                );
                changed();
                location.hash = `code/${fork.id}/edit${context}`;
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <GitFork size={17} />
            Fork code
          </button>
          {owner && (
            <>
              <a className="button secondary" href={`#code/${id}/edit${context}`}>
                Edit my code
              </a>
              <button className="button secondary" onClick={() => setSharing(!sharing)}>
                Share with user
              </button>
            </>
          )}
        </div>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {owner && (
        <button
          className="button secondary"
          onClick={async () => {
            try {
              const value = await api<{ private: boolean }>(`/code/${id}/visibility`, {
                method: 'PUT',
                body: JSON.stringify({ visibility: data.private ? 'public' : 'private' }),
              });
              setData({ ...data, private: value.private });
              setNotice(
                value.private
                  ? 'Notebook is private. Invited users retain read access.'
                  : 'Published snapshot is public.',
              );
              changed();
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        >
          {data.private ? 'Make published snapshot public' : 'Make notebook private'}
        </button>
      )}

      {sharing && owner && (
        <section className="code-sharing">
          <h2>Share with a user</h2>
          <p>
            Sharing grants read access and adds this notebook to the recipient’s Shared with you
            filter. You can revoke access below.
          </p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              setBusy(true);
              setError('');
              try {
                await api(`/code/${id}/shares`, {
                  method: 'POST',
                  body: JSON.stringify({ username }),
                });
                setNotice(`Shared with ${username}`);
                setUsername('');
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Recipient username
              <input
                required
                minLength={3}
                maxLength={40}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <button className="button secondary" disabled={busy}>
              Share code
            </button>
          </form>
          <ul>
            {shares.map((recipient) => (
              <li key={recipient.id}>
                {recipient.username}
                <button
                  disabled={busy}
                  className="text-button"
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api(`/code/${id}/shares/${recipient.id}`, { method: 'DELETE' });
                      setShares((values) => values.filter((row) => row.id !== recipient.id));
                      setNotice(`Sharing removed for ${recipient.username}`);
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Remove sharing
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="competition-description">{data.description}</p>
      <div className="code-view-tabs" role="tablist" aria-label="Code details">
        {viewTabs.map((name, index) => (
          <button
            key={name}
            role="tab"
            id={`code-tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`code-panel-${name}`}
            tabIndex={tab === name ? 0 : -1}
            onClick={() => setTab(name)}
            onKeyDown={(event) => {
              const next =
                event.key === 'ArrowRight'
                  ? (index + 1) % viewTabs.length
                  : event.key === 'ArrowLeft'
                    ? (index + viewTabs.length - 1) % viewTabs.length
                    : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? viewTabs.length - 1
                        : null;
              if (next !== null) {
                event.preventDefault();
                setTab(viewTabs[next]);
                window.document.getElementById(`code-tab-${viewTabs[next]}`)?.focus();
              }
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="code-panel-Notebook"
        aria-labelledby="code-tab-Notebook"
        hidden={tab !== 'Notebook'}
      >
        <div className="code-view-layout">
          <section
            ref={publishedCells}
            className="code-published-cells"
            aria-label="Published notebook"
          >
            {data.document.cells.length ? (
              data.document.cells.map((cell, index) => (
                <article className="code-published-cell" key={cell.id || index}>
                  {cell.cell_type === 'markdown' ? (
                    <Markdown>{text(cell.source)}</Markdown>
                  ) : cell.cell_type === 'raw' ? (
                    <pre>{text(cell.source)}</pre>
                  ) : (
                    <>
                      <div className="code-cell-label">
                        <Code2 size={15} />
                        Cell {index + 1} · [{cell.execution_count ?? ' '}]
                      </div>
                      <CodeMirror
                        value={text(cell.source)}
                        extensions={[python()]}
                        editable={false}
                        readOnly
                        basicSetup={{
                          lineNumbers: true,
                          foldGutter: true,
                          highlightActiveLine: false,
                          highlightActiveLineGutter: false,
                        }}
                      />
                      {!!cell.outputs?.length && (
                        <div
                          className="arena-cell-outputs"
                          aria-label={`Published output cell ${index + 1}`}
                        >
                          {cell.outputs.map((output, i) => (
                            <CellOutput key={i} output={output} />
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </article>
              ))
            ) : (
              <p>This notebook has no published cells.</p>
            )}
          </section>
          <aside className="code-view-sidebar">
            <section aria-label="Table of contents">
              <h2>Table of contents</h2>
              <nav className="code-outline" aria-label="Notebook headings">
                {headings.length ? (
                  headings.map((heading) => (
                    <button
                      key={heading.id}
                      style={{ paddingLeft: `${12 + (heading.level - 1) * 12}px` }}
                      onClick={() => {
                        const target = window.document.getElementById(heading.id);
                        target?.scrollIntoView({ block: 'start', behavior: 'smooth' });
                        target?.focus({ preventScroll: true });
                      }}
                    >
                      {heading.title}
                    </button>
                  ))
                ) : (
                  <p>No headings in this notebook.</p>
                )}
              </nav>
            </section>
            <section>
              <h2>
                <Database size={18} />
                Inputs
              </h2>
              {data.inputs.length ? (
                <ul>
                  {data.inputs.map((input) => (
                    <li key={input.id}>
                      <strong>{input.title}</strong>
                      <small>{input.filename}</small>
                      {input.available ? (
                        <a href={`/api/datasets/${input.id}/download`}>Download input</a>
                      ) : (
                        <span>Source no longer available</span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No catalog inputs attached. Data may be embedded in the code.</p>
              )}
            </section>
            <section>
              <h2>
                <FileOutput size={18} />
                Outputs
              </h2>
              <p>
                {outputs
                  ? `${outputs} saved cell outputs, displayed alongside the code.`
                  : 'No outputs have been published yet.'}
              </p>
              <p className="muted">
                This page does not run code. Fork a copy to execute your own experiment.
              </p>
            </section>
            <section>
              <h2>Competitions</h2>
              {data.competitions.length ? (
                data.competitions.map((item) => (
                  <p key={item.id}>
                    <a href={`#competitions/${item.id}/code`}>{item.title}</a>
                  </p>
                ))
              ) : (
                <p>Not linked to a competition.</p>
              )}
            </section>
          </aside>
        </div>
      </div>
      <section
        role="tabpanel"
        id="code-panel-Input"
        aria-labelledby="code-tab-Input"
        hidden={tab !== 'Input'}
        className="code-tab-content"
      >
        <h2>Input</h2>
        {data.inputs.length ? (
          data.inputs.map((input) => (
            <article key={input.id} className="code-published-cell">
              <h3>{input.title}</h3>
              <p>{input.filename}</p>
              {input.available ? (
                <a className="button secondary" href={`/api/datasets/${input.id}/download`}>
                  Download input
                </a>
              ) : (
                <p>Source no longer available.</p>
              )}
            </article>
          ))
        ) : (
          <p>No catalog inputs attached to this published notebook.</p>
        )}
      </section>
      {(['Output', 'Logs'] as const).map((name) => {
        const cells = data.document.cells
          .map((cell, index) => ({
            index,
            outputs: (cell.outputs || []).filter(
              (output) => name === 'Output' || ['stream', 'error'].includes(output.output_type),
            ),
          }))
          .filter((cell) => cell.outputs.length);
        return (
          <section
            key={name}
            role="tabpanel"
            id={`code-panel-${name}`}
            aria-labelledby={`code-tab-${name}`}
            hidden={tab !== name}
            className="code-tab-content"
          >
            <h2>{name}</h2>
            <p>
              {name === 'Logs'
                ? 'Saved notebook stdout, stderr, and errors from the published version.'
                : 'Saved cell results from the published version.'}
            </p>
            {cells.length ? (
              cells.map((cell) => (
                <article key={cell.index} className="code-published-cell">
                  <h3>Cell {cell.index + 1}</h3>
                  <div className="arena-cell-outputs">
                    {cell.outputs.map((output, index) => (
                      <CellOutput key={index} output={output} />
                    ))}
                  </div>
                </article>
              ))
            ) : (
              <p>
                {name === 'Logs'
                  ? 'No execution logs have been published.'
                  : 'No outputs have been published.'}
              </p>
            )}
          </section>
        );
      })}
      <section
        role="tabpanel"
        id="code-panel-Comments"
        aria-labelledby="code-tab-Comments"
        hidden={tab !== 'Comments'}
        className="code-tab-content"
      >
        {tab === 'Comments' && <CodeComments key={id} id={id} user={user} signIn={signIn} />}
      </section>
    </article>
  );
}
