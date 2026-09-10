import CommitNotebook from './CommitNotebook';
import { notebookHeadings } from './notebookHeadings';
import PlatformRail from './PlatformRail';
import type { Page } from './navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { tags } from '@lezer/highlight';
import Markdown from './Markdown';
import { markdown } from '@codemirror/lang-markdown';
import DOMPurify from 'dompurify';
import {
  ArrowDown,
  ArrowUp,
  Code2,
  ChevronDown,
  ChevronsRight,
  Scissors,
  Copy,
  Clipboard,
  PanelRight,
  Terminal,
  Keyboard,
  X,
  FileText,
  Play,
  Plus,
  RotateCcw,
  Save,
  Square,
  Trash2,
} from 'lucide-react';
import { api } from './api';
import NotebookPanel from './NotebookPanel';

const notebookHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: tags.keyword, color: '#008000', fontWeight: '600' },
    { tag: tags.comment, color: '#5a8c91', fontStyle: 'italic' },
    { tag: tags.string, color: '#d32f40' },
    { tag: tags.number, color: '#1976b8' },
    { tag: tags.function(tags.variableName), color: '#1764a0' },
  ]),
);

export type Output = {
  output_type: string;
  text?: string | string[];
  data?: Record<string, string | string[]>;
  ename?: string;
  evalue?: string;
  traceback?: string[];
  execution_count?: number;
  metadata?: object;
  transient?: { display_id?: string };
};
export type Cell = {
  id: string;
  cell_type: 'code' | 'markdown' | 'raw';
  source: string | string[];
  metadata: object;
  outputs?: Output[];
  execution_count?: number | null;
};
export type Document = {
  nbformat: 4;
  nbformat_minor: number;
  metadata: Record<string, unknown>;
  cells: Cell[];
};
export const text = (value?: string | string[]) =>
  Array.isArray(value)
    ? value.filter((line) => typeof line === 'string').join('')
    : typeof value === 'string'
      ? value
      : '';
const newCell = (type: Cell['cell_type'] = 'code'): Cell => ({
  id: crypto.randomUUID(),
  cell_type: type,
  source: '',
  metadata: {},
  ...(type === 'code' ? { outputs: [], execution_count: null } : {}),
});
const blank = (code: string): Document => ({
  nbformat: 4,
  nbformat_minor: 5,
  metadata: { kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' } },
  cells: [{ ...newCell(), source: code }],
});

export function CellOutput({ output }: { output: Output }) {
  if (output.data?.['text/csv']) {
    const csv = text(output.data['text/csv']);
    return (
      <a href={`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`} download="submission.csv">
        Download CSV
      </a>
    );
  }
  if (output.output_type === 'error')
    return (
      <pre className="cell-error">
        {(
          (Array.isArray(output.traceback)
            ? output.traceback.filter((line) => typeof line === 'string').join('\n')
            : '') || `${text(output.ename)}: ${text(output.evalue)}`
        ).replace(/\u001b\[[0-9;]*m/g, '')}
      </pre>
    );
  if (output.output_type === 'stream') return <pre>{text(output.text)}</pre>;
  const data = output.data || {};
  if (data['image/png'])
    return (
      <img
        className="cell-plot"
        alt="Python plot output"
        src={`data:image/png;base64,${text(data['image/png'])}`}
      />
    );
  if (data['image/jpeg'])
    return (
      <img
        className="cell-plot"
        alt="Python image output"
        src={`data:image/jpeg;base64,${text(data['image/jpeg'])}`}
      />
    );
  if (data['text/html'])
    return (
      <div
        className="cell-rich-output"
        dangerouslySetInnerHTML={{
          __html: DOMPurify.sanitize(text(data['text/html']), {
            USE_PROFILES: { html: true },
            FORBID_TAGS: ['style', 'form', 'input', 'button', 'iframe', 'object', 'embed'],
          }),
        }}
      />
    );
  if (data['text/markdown']) return <Markdown>{text(data['text/markdown'])}</Markdown>;
  return <pre>{text(data['text/plain'])}</pre>;
}

export default function NotebookWorkspace({
  notebookId,
  signedIn,
  signIn,
  draftId,
  autoStart = false,
  onSaveDraft,
  onSavingChange,
  initialCode = '',
  title = 'Untitled notebook',
  onTitleChange,
  onClose,
  onNavigate,
  permanent = false,
  canPublish = false,
  competitionId,
}: {
  notebookId: number;
  signedIn: boolean;
  signIn: () => void;
  draftId?: string;
  autoStart?: boolean;
  onSaveDraft?: () => Promise<void>;
  onSavingChange?: (saving: boolean) => void;
  initialCode?: string;
  title?: string;
  onTitleChange?: (value: string) => void;
  onClose?: () => void;
  onNavigate?: (page: Page) => void;
  permanent?: boolean;
  canPublish?: boolean;
  competitionId?: number;
}) {
  const [document, setDocument] = useState<Document>(() => blank(initialCode));
  const doc = useRef(document);
  const [state, setState] = useState<'idle' | 'starting' | 'ready'>('idle');
  const [running, setRunning] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [savedAt, setSavedAt] = useState('');
  const [published, setPublished] = useState(false);
  const [active, setActive] = useState('');
  const [preview, setPreview] = useState<Record<string, boolean>>({});
  const [dark, setDark] = useState(false);
  const [navigationExpanded, setNavigationExpanded] = useState(false);
  const [panel, setPanel] = useState(() => window.innerWidth > 760);
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [consoleCommand, setConsoleCommand] = useState('');
  const [consoleOutputs, setConsoleOutputs] = useState<Output[]>([]);
  const consoleCell = useRef<Cell>({ ...newCell(), id: 'console' });
  const [menu, setMenu] = useState('');
  const [lineNumbers, setLineNumbers] = useState(false);
  const [help, setHelp] = useState(false);
  const clipboard = useRef<Cell | null>(null);
  const [hasClipboard, setHasClipboard] = useState(false);
  const menuBar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!menuBar.current?.contains(event.target as Node)) setMenu('');
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && (menu || help)) {
        event.preventDefault();
        event.stopPropagation();
        setMenu('');
        setHelp(false);
      }
    };
    window.addEventListener('pointerdown', close);
    window.addEventListener('keydown', escape, true);
    return () => {
      window.removeEventListener('pointerdown', close);
      window.removeEventListener('keydown', escape, true);
    };
  }, [menu, help]);
  const alive = useRef(true);
  const runController = useRef<AbortController | null>(null);
  const runInProgress = useRef(false);
  const saveInProgress = useRef(false);
  const stopRequested = useRef(false);
  const generation = useRef(0);
  const base = `/editor/${draftId ? 'drafts' : 'notebooks'}/${draftId || notebookId}`;

  function update(change: (previous: Document) => Document, edited = true) {
    doc.current = change(doc.current);
    setDocument(doc.current);
    if (edited) setDirty(true);
  }
  function changeCell(id: string, change: Partial<Cell>) {
    if (id === 'console') {
      consoleCell.current = { ...consoleCell.current, ...change };
      setConsoleOutputs(consoleCell.current.outputs || []);
      return;
    }
    update((previous) => ({
      ...previous,
      cells: previous.cells.map((cell) => (cell.id === id ? { ...cell, ...change } : cell)),
    }));
  }
  async function launch() {
    if (!signedIn) {
      signIn();
      return;
    }
    const version = ++generation.current;
    setState('starting');
    setError('');
    try {
      let session = await api<{ state: string }>('/notebook-session', { method: 'POST' });
      const deadline = Date.now() + 240000;
      while (session.state !== 'ready') {
        if (!alive.current || version !== generation.current) return;
        if (Date.now() > deadline || session.state === 'stopping')
          throw new Error('Runtime is not ready. Please retry shortly.');
        await new Promise((resolve) => setTimeout(resolve, 1500));
        session = await api('/notebook-session');
      }
      if (!alive.current || version !== generation.current) return;
      const loaded = await api<Document>(`${base}/document`);
      if (!alive.current || version !== generation.current) return;
      loaded.cells = loaded.cells.map((cell) => ({ ...cell, id: cell.id || crypto.randomUUID() }));
      if (!loaded.cells.length) loaded.cells.push(newCell());
      if (draftId && loaded.cells.length === 1 && !text(loaded.cells[0].source).trim()) {
        loaded.cells[0].source =
          '# Python libraries for data analysis\nimport numpy as np\nimport pandas as pd\n\n# Use Add Input to add a dataset loader.\n# Write code below, then press Shift+Enter to run.\n';
      }
      update(() => loaded, false);
      setDirty(false);
      setActive(loaded.cells[0].id);
      setState('ready');
      setPreview(
        Object.fromEntries(
          loaded.cells
            .filter((cell) => cell.cell_type === 'markdown')
            .map((cell) => [cell.id, true]),
        ),
      );
    } catch (e) {
      if (alive.current) {
        setError((e as Error).message);
        setState('idle');
      }
    }
  }
  useEffect(() => {
    alive.current = true;
    if (autoStart) void launch();
    return () => {
      alive.current = false;
      generation.current++;
      runController.current?.abort();
    };
  }, []);

  async function save() {
    if (state !== 'ready' || runInProgress.current || saveInProgress.current) return false;
    saveInProgress.current = true;
    setSaving(true);
    onSavingChange?.(true);
    setError('');
    const snapshot = doc.current;
    try {
      await api(`${base}/document`, { method: 'PUT', body: JSON.stringify(snapshot) });
      await onSaveDraft?.();
      if (alive.current) {
        setDirty(doc.current !== snapshot);
        setSavedAt(new Date().toLocaleTimeString());
      }
      return true;
    } catch (e) {
      if (alive.current) setError((e as Error).message);
      return false;
    } finally {
      saveInProgress.current = false;
      if (alive.current) setSaving(false);
      onSavingChange?.(false);
    }
  }
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void saveRef.current();
      }
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);

  async function executeCell(cell: Cell) {
    if (cell.cell_type !== 'code') {
      setPreview((previous) => ({ ...previous, [cell.id]: true }));
      return true;
    }
    setRunning(cell.id);
    changeCell(cell.id, { outputs: [], execution_count: null });
    const controller = new AbortController();
    runController.current = controller;
    const response = await fetch(`/api${base}/execute`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Arena-Client': 'web' },
      body: JSON.stringify({ code: text(cell.source) }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Execution failed');
    }
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let failed = false;
    let completed = false;
    let clearNext = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop()!;
      for (const line of lines.filter(Boolean)) {
        const message = JSON.parse(line);
        if (message.type === 'failure') throw new Error(message.message);
        if (message.type === 'done') {
          completed = true;
          continue;
        }
        const content = message.content;
        const current =
          cell.id === 'console'
            ? consoleCell.current
            : doc.current.cells.find((item) => item.id === cell.id);
        if (!current) continue;
        if (message.type === 'execute_input') {
          changeCell(cell.id, { execution_count: content.execution_count });
          continue;
        }
        if (message.type === 'clear_output') {
          if (content.wait) clearNext = true;
          else changeCell(cell.id, { outputs: [] });
          continue;
        }
        let outputs = clearNext ? [] : [...(current.outputs || [])];
        clearNext = false;
        if (message.type === 'update_display_data') {
          outputs = outputs.map((output) =>
            output.transient?.display_id === content.transient?.display_id
              ? { ...output, data: content.data }
              : output,
          );
        } else {
          if (message.type === 'error') failed = true;
          outputs.push({ ...content, output_type: message.type });
        }
        changeCell(cell.id, { outputs });
      }
    }
    if (!completed) throw new Error('The execution connection ended. Check the cell and retry.');
    return !failed;
  }
  async function run(all = false, id = active) {
    if (state !== 'ready' || runInProgress.current || saving) return;
    runInProgress.current = true;
    stopRequested.current = false;
    setError('');
    try {
      for (const cell of all
        ? [...doc.current.cells]
        : doc.current.cells.filter((cell) => cell.id === id)) {
        if (stopRequested.current || !alive.current) break;
        if (!(await executeCell(cell))) break;
      }
    } catch (e) {
      if (alive.current && (e as Error).name !== 'AbortError') setError((e as Error).message);
    } finally {
      runInProgress.current = false;
      if (alive.current) setRunning(null);
    }
  }
  async function control(action: 'interrupt' | 'restart') {
    stopRequested.current = true;
    setControlling(true);
    try {
      await api(`${base}/kernel/${action}`, { method: 'POST' });
      if (action === 'restart')
        update((previous) => ({
          ...previous,
          cells: previous.cells.map((cell) => ({ ...cell, execution_count: null })),
        }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setControlling(false);
    }
  }
  function insert(type: Cell['cell_type'], source = '') {
    const cell = { ...newCell(type), source };
    const index = doc.current.cells.findIndex((item) => item.id === active);
    update((previous) => ({
      ...previous,
      cells: [...previous.cells.slice(0, index + 1), cell, ...previous.cells.slice(index + 1)],
    }));
    setActive(cell.id);
  }
  function move(id: string, delta: number) {
    const cells = [...doc.current.cells];
    const index = cells.findIndex((cell) => cell.id === id);
    const next = index + delta;
    if (next < 0 || next >= cells.length) return;
    [cells[index], cells[next]] = [cells[next], cells[index]];
    update((previous) => ({ ...previous, cells }));
  }
  const busy = state !== 'ready' || !!running || saving || controlling;
  const selected = document.cells.find((cell) => cell.id === active) || document.cells[0];
  const inputs = (document.metadata.arena_inputs || []) as {
    id: number;
    title: string;
    filename?: string;
  }[];
  const headings = useMemo(
    () =>
      document.cells
        .filter((cell) => cell.cell_type === 'markdown')
        .flatMap((cell) =>
          notebookHeadings(text(cell.source)).map((heading, index) => ({
            ...heading,
            id: `${cell.id}-heading-${index}`,
            cellId: cell.id,
            index,
          })),
        ),
    [document.cells],
  );
  function copyCell(cut = false) {
    if (!selected || busy) return;
    clipboard.current = structuredClone(selected);
    setHasClipboard(true);
    if (cut) {
      const cells = doc.current.cells.filter((cell) => cell.id !== selected.id);
      if (!cells.length) cells.push(newCell());
      update((previous) => ({ ...previous, cells }));
      setActive(cells[0].id);
    }
  }
  function pasteCell() {
    if (!clipboard.current || busy) return;
    const cell = { ...structuredClone(clipboard.current), id: crypto.randomUUID() };
    const index = doc.current.cells.findIndex((item) => item.id === active);
    update((previous) => ({
      ...previous,
      cells: [...previous.cells.slice(0, index + 1), cell, ...previous.cells.slice(index + 1)],
    }));
    setActive(cell.id);
  }
  async function runConsole() {
    if (busy || runInProgress.current || !consoleCommand.trim()) return;
    const code = consoleCommand;
    setConsoleCommand('');
    runInProgress.current = true;
    setError('');
    try {
      await executeCell({ ...newCell(), id: 'console', source: code });
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      runInProgress.current = false;
      if (alive.current) setRunning(null);
    }
  }
  async function attach(item: { id: number; title: string; filename?: string }) {
    const { path } = await api<{ path: string }>(`${base}/inputs/${item.id}`, { method: 'POST' });
    update((previous) => ({
      ...previous,
      metadata: { ...previous.metadata, arena_inputs: [...inputs, { ...item, path }] },
    }));
    insert(
      'code',
      `import pandas as pd\n\n# Arena dataset ${item.id}\ndf = pd.read_csv(${JSON.stringify(path)})\ndf.head()`,
    );
  }
  const actions: Record<string, { label: string; action: () => void; disabled?: boolean }[]> = {
    File: [
      { label: 'Save notebook', action: () => void save(), disabled: busy },
      {
        label: 'Download saved notebook',
        action: () => {
          window.location.href = `/api/notebooks/${notebookId}/working-copy`;
        },
        disabled: !!draftId || busy,
      },
    ],
    Edit: [
      { label: 'Cut cell', action: () => copyCell(true), disabled: busy },
      { label: 'Copy cell', action: () => copyCell(), disabled: busy },
      { label: 'Paste cell', action: pasteCell, disabled: busy || !hasClipboard },
      {
        label: 'Clear all outputs',
        action: () =>
          update((previous) => ({
            ...previous,
            cells: previous.cells.map((cell) =>
              cell.cell_type === 'code' ? { ...cell, outputs: [], execution_count: null } : cell,
            ),
          })),
        disabled: busy,
      },
    ],
    View: [
      { label: `${panel ? 'Hide' : 'Show'} notebook panel`, action: () => setPanel(!panel) },
      {
        label: `${consoleOpen ? 'Hide' : 'Show'} console`,
        action: () => setConsoleOpen(!consoleOpen),
      },
      {
        label: `${lineNumbers ? 'Hide' : 'Show'} line numbers`,
        action: () => setLineNumbers(!lineNumbers),
      },
    ],
    Run: [
      { label: 'Run selected cell', action: () => void run(), disabled: busy },
      { label: 'Run all cells', action: () => void run(true), disabled: busy },
      {
        label: 'Interrupt execution',
        action: () => void control('interrupt'),
        disabled: !running || controlling,
      },
      { label: 'Restart Python kernel', action: () => void control('restart'), disabled: busy },
    ],
    Settings: [
      { label: dark ? 'Use light theme' : 'Use dark theme', action: () => setDark(!dark) },
    ],
    'Add-ons': [{ label: 'Add a dataset input', action: () => setPanel(true) }],
    Help: [{ label: 'Keyboard shortcuts and notebook help', action: () => setHelp(true) }],
  };
  return (
    <section
      className={`arena-notebook ${dark ? 'arena-notebook-dark' : ''} ${navigationExpanded ? 'navigation-expanded' : ''}`}
      aria-label="Arena notebook editor"
    >
      <PlatformRail
        expanded={navigationExpanded}
        toggle={() => setNavigationExpanded(!navigationExpanded)}
        signedIn={signedIn}
        permanent={permanent || notebookId > 0}
        disabled={saving}
        navigate={(page) => {
          if (onNavigate) onNavigate(page);
          else {
            onClose?.();
            window.location.hash = page;
          }
        }}
      />
      <header className="notebook-topbar new-notebook-header">
        <div className="notebook-title-row">
          {onTitleChange ? (
            <input
              aria-label="Notebook title"
              value={title}
              maxLength={160}
              minLength={3}
              onChange={(event) => {
                onTitleChange(event.target.value);
                setDirty(true);
              }}
            />
          ) : (
            <h1>{title}</h1>
          )}
          <span className="notebook-save-state">
            {dirty
              ? 'Unsaved changes'
              : savedAt
                ? 'Saved permanently'
                : draftId
                  ? 'Temporary draft'
                  : 'Private working copy'}
          </span>
          <button
            className="notebook-save-button"
            aria-label="Save"
            disabled={busy}
            onClick={() => void save()}
          >
            <Save size={17} />
            {saving ? 'Saving…' : 'Save notebook'}
            <span>{permanent || savedAt ? '✓' : '0'}</span>
          </button>
          {competitionId && notebookId > 0 && (
            <CommitNotebook
              notebookId={notebookId}
              competitionId={competitionId}
              save={save}
              close={onClose}
              disabled={busy}
            />
          )}
          {competitionId && !notebookId && (
            <span className="muted">Save to enable competition commit</span>
          )}
          {canPublish && !draftId && !competitionId && (
            <button
              className="button secondary"
              disabled={busy || state !== 'ready'}
              onClick={async () => {
                setSaving(true);
                setError('');
                try {
                  await api(`/code/${notebookId}/publication`, {
                    method: 'PUT',
                    body: JSON.stringify(doc.current),
                  });
                  setPublished(true);
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setSaving(false);
                }
              }}
            >
              Publish code and outputs
            </button>
          )}
          {published && <a href={`#code/${notebookId}`}>View published code</a>}
          {onClose && (
            <button
              className="notebook-close"
              aria-label="Close notebook editor"
              disabled={saving}
              onClick={onClose}
            >
              <X size={21} />
            </button>
          )}
        </div>
        <div className="notebook-menubar" ref={menuBar}>
          {Object.entries(actions).map(([name, entries]) => (
            <div className="notebook-menu" key={name}>
              <button
                aria-haspopup="menu"
                aria-expanded={menu === name}
                onClick={() => setMenu(menu === name ? '' : name)}
              >
                {name}
              </button>
              {menu === name && (
                <div className="notebook-menu-popover" role="menu">
                  {entries.map((entry) => (
                    <button
                      role="menuitem"
                      key={entry.label}
                      disabled={entry.disabled}
                      onClick={() => {
                        entry.action();
                        setMenu('');
                      }}
                    >
                      {entry.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </header>
      <div className={`notebook-body ${panel ? '' : 'notebook-panel-hidden'}`}>
        <div className="notebook-main">
          <header className="arena-notebook-toolbar">
            <button
              aria-label="Add code cell"
              title="Add code cell"
              disabled={busy}
              onClick={() => insert('code')}
            >
              <Plus size={22} />
            </button>
            <span className="notebook-tool-divider" />
            <button
              aria-label="Cut cell"
              title="Cut cell"
              disabled={busy}
              onClick={() => copyCell(true)}
            >
              <Scissors size={21} />
            </button>
            <button
              aria-label="Copy cell"
              title="Copy cell"
              disabled={busy}
              onClick={() => copyCell()}
            >
              <Copy size={21} />
            </button>
            <button
              aria-label="Paste cell"
              title="Paste cell"
              disabled={busy || !hasClipboard}
              onClick={pasteCell}
            >
              <Clipboard size={21} />
            </button>
            <span className="notebook-tool-divider" />
            <button
              aria-label="Run cell"
              title="Run cell · Shift+Enter"
              disabled={busy}
              onClick={() => void run()}
            >
              <Play size={19} />
            </button>
            <button aria-label="Run all" disabled={busy} onClick={() => void run(true)}>
              <ChevronsRight size={22} /> Run All
            </button>
            <span className="notebook-tool-divider" />
            <select
              aria-label="Cell type"
              value={selected?.cell_type || 'code'}
              disabled={busy}
              onChange={(event) =>
                changeCell(selected.id, {
                  cell_type: event.target.value as Cell['cell_type'],
                  outputs: [],
                  execution_count: null,
                })
              }
            >
              <option value="code">Code</option>
              <option value="markdown">Markdown</option>
              <option value="raw">Raw</option>
            </select>
            <span className="native-kernel">
              <span
                className={`kernel-dot ${running ? 'busy' : state === 'ready' ? 'online' : ''}`}
              />
              {running
                ? 'Session running'
                : state === 'ready'
                  ? 'Session ready'
                  : state === 'starting'
                    ? 'Starting session…'
                    : 'Session off'}
            </span>
            {state === 'idle' && <button onClick={() => void launch()}>Start session</button>}
            <button
              aria-label="Interrupt"
              title="Interrupt"
              disabled={!running || controlling}
              onClick={() => void control('interrupt')}
            >
              <Square size={18} />
            </button>
            <button
              aria-label="Restart kernel"
              title="Restart kernel"
              disabled={busy}
              onClick={() => void control('restart')}
            >
              <RotateCcw size={19} />
            </button>
            <button
              aria-label="Toggle notebook panel"
              title="Notebook panel"
              onClick={() => setPanel(!panel)}
            >
              <PanelRight size={18} />
            </button>
          </header>
          {error && (
            <p className="error native-notebook-error" role="alert">
              {error}
            </p>
          )}
          {state === 'starting' && (
            <p className="native-notebook-loading" role="status">
              Starting your Python runtime… Your notebook will be ready shortly.
            </p>
          )}
          <div className="arena-cells">
            {document.cells.map((cell, index) => (
              <article
                key={cell.id}
                id={`cell-${cell.id}`}
                className={`arena-cell ${active === cell.id ? 'active' : ''}`}
                onFocus={() => setActive(cell.id)}
                onClick={() => setActive(cell.id)}
                onKeyDown={(event) => {
                  if (event.shiftKey && event.key === 'Enter') {
                    event.preventDefault();
                    void run(false, cell.id);
                  }
                }}
              >
                <div className="arena-cell-heading">
                  <span>
                    {cell.cell_type === 'code'
                      ? `[${running === cell.id ? '*' : (cell.execution_count ?? ' ')}]`
                      : ''}{' '}
                    <small>Cell {index + 1}</small>
                  </span>
                  <div>
                    <button
                      aria-label={`Run cell ${index + 1}`}
                      disabled={state !== 'ready' || !!running || saving || controlling}
                      onClick={() => void run(false, cell.id)}
                    >
                      <Play size={14} />
                    </button>
                    {cell.cell_type !== 'code' && (
                      <button
                        onClick={() =>
                          setPreview((previous) => ({ ...previous, [cell.id]: !previous[cell.id] }))
                        }
                      >
                        {preview[cell.id] ? 'Edit Markdown' : 'Preview'}
                      </button>
                    )}
                    <button
                      aria-label={`Move cell ${index + 1} up`}
                      disabled={index === 0 || !!running || saving}
                      onClick={() => move(cell.id, -1)}
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      aria-label={`Move cell ${index + 1} down`}
                      disabled={index === document.cells.length - 1 || !!running || saving}
                      onClick={() => move(cell.id, 1)}
                    >
                      <ArrowDown size={14} />
                    </button>
                    <button
                      aria-label={`Delete cell ${index + 1}`}
                      disabled={document.cells.length === 1 || !!running || saving}
                      onClick={() =>
                        update((previous) => ({
                          ...previous,
                          cells: previous.cells.filter((item) => item.id !== cell.id),
                        }))
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
                {cell.cell_type === 'markdown' && !preview[cell.id] && (
                  <div
                    className="markdown-formatting"
                    role="toolbar"
                    aria-label={`Format Markdown cell ${index + 1}`}
                  >
                    {[
                      ['Heading', '## Heading'],
                      ['Bold', '**bold text**'],
                      ['Italic', '*italic text*'],
                      ['Link', '[link text](https://example.com)'],
                      ['List', '- List item'],
                      ['Math', '$x^2$'],
                    ].map(([label, snippet]) => (
                      <button
                        key={label}
                        disabled={saving || !!running || state !== 'ready'}
                        onClick={() =>
                          changeCell(cell.id, {
                            source: `${text(cell.source)}${text(cell.source) ? '\n' : ''}${snippet}`,
                          })
                        }
                      >
                        {label}
                      </button>
                    ))}
                    <span>Shift + Enter to preview · double-click preview to edit</span>
                  </div>
                )}
                {cell.cell_type === 'markdown' && preview[cell.id] ? (
                  <div
                    className="arena-markdown"
                    tabIndex={0}
                    aria-label={`Markdown preview cell ${index + 1}`}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        setPreview((previous) => ({ ...previous, [cell.id]: false }));
                      }
                    }}
                    onDoubleClick={() =>
                      setPreview((previous) => ({ ...previous, [cell.id]: false }))
                    }
                  >
                    <Markdown>{text(cell.source) || '*Empty Markdown cell*'}</Markdown>
                  </div>
                ) : (
                  <CodeMirror
                    aria-label={`${cell.cell_type === 'code' ? 'Code' : 'Markdown'} cell ${index + 1}`}
                    value={text(cell.source)}
                    extensions={
                      cell.cell_type === 'code'
                        ? [python(), ...(dark ? [] : [notebookHighlight])]
                        : cell.cell_type === 'markdown'
                          ? [markdown()]
                          : []
                    }
                    theme={dark ? 'dark' : 'light'}
                    editable={state === 'ready' && !saving && !running}
                    minHeight="90px"
                    onChange={(value) => changeCell(cell.id, { source: value })}
                    basicSetup={{
                      lineNumbers: lineNumbers && cell.cell_type === 'code',
                      foldGutter: false,
                      highlightActiveLine: false,
                    }}
                  />
                )}
                {!!cell.outputs?.length && (
                  <div className="arena-cell-outputs" aria-label={`Output cell ${index + 1}`}>
                    {cell.outputs.map((output, i) => (
                      <CellOutput key={i} output={output} />
                    ))}
                  </div>
                )}
              </article>
            ))}
            <div className="arena-add-cell">
              <button
                disabled={state !== 'ready' || !!running || saving || controlling}
                onClick={() => insert('code')}
              >
                <Plus size={15} />
                <Code2 size={16} />
                Code
              </button>
              <button
                disabled={state !== 'ready' || !!running || saving || controlling}
                onClick={() => insert('markdown')}
              >
                <Plus size={15} />
                <FileText size={16} />
                Markdown
              </button>
            </div>
          </div>
          {consoleOpen && (
            <section className="notebook-console" aria-label="Python console">
              <header>
                <button onClick={() => setConsoleOpen(false)}>
                  Console <X size={17} />
                </button>
                <button
                  aria-label="Clear console"
                  disabled={!!running}
                  onClick={() => {
                    consoleCell.current.outputs = [];
                    setConsoleOutputs([]);
                  }}
                >
                  <Trash2 size={15} /> Clear
                </button>
              </header>
              <div className="notebook-console-output" aria-live="polite">
                {consoleOutputs.length ? (
                  consoleOutputs.map((output, index) => <CellOutput key={index} output={output} />)
                ) : (
                  <pre>
                    {state === 'ready'
                      ? 'Your notebook is connected to a Python runtime.\nEnter Python code below and press Enter.'
                      : 'Start a session to execute Python commands.'}
                  </pre>
                )}
              </div>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void runConsole();
                }}
              >
                <ChevronDown size={17} />
                <input
                  aria-label="Console command"
                  placeholder="Enter console command here"
                  value={consoleCommand}
                  disabled={busy}
                  onChange={(event) => setConsoleCommand(event.target.value)}
                />
                <button
                  type="submit"
                  disabled={busy || !consoleCommand.trim()}
                  aria-label="Execute console command"
                >
                  <Play size={15} />
                </button>
              </form>
            </section>
          )}
          <footer className="arena-notebook-footer">
            <div>
              <button
                aria-label="Toggle Python console"
                onClick={() => setConsoleOpen(!consoleOpen)}
              >
                <Terminal size={18} />
              </button>
              <button aria-label="Keyboard shortcuts" onClick={() => setHelp(true)}>
                <Keyboard size={18} />
              </button>
            </div>
            <div className="arena-notebook-subbar">
              <span>
                {dirty
                  ? 'Unsaved changes'
                  : savedAt
                    ? `Saved ${savedAt}`
                    : draftId
                      ? 'Temporary · Save to keep'
                      : 'Private working copy'}
              </span>
              <span>{document.cells.length} cells</span>
            </div>
          </footer>
        </div>
        {panel && (
          <NotebookPanel
            close={() => setPanel(false)}
            inputs={inputs}
            attach={attach}
            headings={headings}
            jump={(id) => {
              const heading = headings.find((item) => item.id === id);
              if (!heading) return;
              if (window.innerWidth <= 760) setPanel(false);
              setActive(heading.cellId);
              setPreview((previous) => ({ ...previous, [heading.cellId]: true }));
              requestAnimationFrame(() => {
                const target = window.document
                  .getElementById(`cell-${heading.cellId}`)
                  ?.querySelectorAll<HTMLElement>(
                    '.arena-markdown h1, .arena-markdown h2, .arena-markdown h3, .arena-markdown h4, .arena-markdown h5, .arena-markdown h6',
                  )[heading.index];
                if (target) {
                  target.tabIndex = -1;
                  target.scrollIntoView({ block: 'start', behavior: 'smooth' });
                  target.focus({ preventScroll: true });
                }
              });
            }}
            ready={!busy}
            notebookId={notebookId}
            draft={!!draftId}
            cellCount={document.cells.length}
            outputCount={document.cells.reduce(
              (count, cell) => count + (cell.outputs?.length || 0),
              0,
            )}
          />
        )}
      </div>
      {help && (
        <div className="notebook-help" role="dialog" aria-label="Notebook help">
          <header>
            <h2>Notebook shortcuts</h2>
            <button aria-label="Close notebook help" onClick={() => setHelp(false)}>
              <X size={20} />
            </button>
          </header>
          <p>
            <kbd>Shift + Enter</kbd> Run selected cell
          </p>
          <p>
            <kbd>Ctrl / ⌘ + S</kbd> Save notebook permanently
          </p>
          <p>
            Double-click Markdown to edit. Use the toolbar to copy, cut, paste, or change a cell’s
            type. The console shares variables with notebook cells.
          </p>
          <p>
            New notebooks remain temporary until you save. Save includes cell sources and outputs.
            Interactive widgets and input prompts are not supported.
          </p>
        </div>
      )}
    </section>
  );
}
