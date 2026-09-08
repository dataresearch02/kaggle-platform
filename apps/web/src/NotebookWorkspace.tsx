import { useEffect, useRef, useState } from 'react';
import {
  Check,
  Code2,
  Download,
  ExternalLink,
  FileText,
  FolderOpen,
  Keyboard,
  ListTree,
  LoaderCircle,
  Moon,
  PanelLeftClose,
  Play,
  RotateCcw,
  Save,
  Square,
  Sun,
} from 'lucide-react';
import { api } from './api';
import {
  execute,
  getLab,
  notebookStatus,
  setFocusMode,
  type LabApp,
  type NotebookStatus,
} from './jupyterBridge';

type State = 'idle' | 'starting' | 'ready' | 'stopping' | 'error';
type Session = { state: 'stopped' | 'starting' | 'ready' | 'stopping' };

export default function NotebookWorkspace({
  notebookId,
  signedIn,
  signIn,
}: {
  notebookId: number;
  signedIn: boolean;
  signIn: () => void;
}) {
  const [state, setState] = useState<State>('idle');
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<NotebookStatus | null>(null);
  const [focus, setFocus] = useState(true);
  const [dark, setDark] = useState(false);
  const [files, setFiles] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [bridgeError, setBridgeError] = useState('');
  const [saved, setSaved] = useState('');
  const iframe = useRef<HTMLIFrameElement>(null);
  const lab = useRef<LabApp | null>(null);
  const focusRef = useRef(focus);
  focusRef.current = focus;

  useEffect(() => {
    lab.current = null;
    setConnected(false);
    setStatus(null);
    setBridgeError('');
    if (!url) return;
    let alive = true;
    let attaching = false;
    const deadline = Date.now() + 60_000;
    const timer = setInterval(async () => {
      const frame = iframe.current;
      if (!frame) return;
      const app = getLab(frame);
      if (!app) {
        if (Date.now() > deadline)
          setBridgeError(
            'Notebook toolbar connection is unavailable. You can still edit in JupyterLab. Restart your server after updating the notebook image.',
          );
        return;
      }
      if (!lab.current && !attaching) {
        attaching = true;
        try {
          await app.restored;
          if (!alive) return;
          lab.current = app;
          setFocusMode(frame, app, focusRef.current);
          setConnected(true);
          setBridgeError('');
        } catch {
          if (alive)
            setBridgeError(
              'Could not connect notebook controls. Use the JupyterLab controls below.',
            );
        }
      }
      if (lab.current && alive) {
        const next = notebookStatus(lab.current);
        setStatus((previous) =>
          JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
        );
      }
    }, 500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [url]);

  async function command(id: string, args: Record<string, unknown> = {}) {
    if (!lab.current) return;
    setError('');
    try {
      await execute(lab.current, id, args);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function save() {
    const context = lab.current?.shell.currentWidget?.context;
    if (!context) return;
    setError('');
    try {
      await context.save();
      setSaved(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    } catch {
      setError('Save failed. Keep this workspace open and retry before stopping the server.');
    }
  }
  async function addCell(markdown: boolean) {
    if (!lab.current) return;
    setError('');
    try {
      await execute(lab.current, 'notebook:insert-cell-below');
      await execute(
        lab.current,
        markdown ? 'notebook:change-cell-to-markdown' : 'notebook:change-cell-to-code',
      );
      await execute(lab.current, 'notebook:enter-edit-mode');
      iframe.current?.contentWindow?.focus();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function toggleFocus() {
    const next = !focus;
    setFocus(next);
    setFiles(false);
    if (iframe.current && lab.current) setFocusMode(iframe.current, lab.current, next);
  }
  function toggleFiles() {
    if (!lab.current) return;
    if (files) lab.current.shell.collapseLeft();
    else lab.current.shell.activateById('filebrowser');
    setFiles(!files);
  }
  async function toggleTheme() {
    if (!lab.current) return;
    try {
      await execute(lab.current, 'apputils:change-theme', {
        theme: dark ? 'JupyterLab Light' : 'JupyterLab Dark',
      });
      setDark(!dark);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const generation = useRef(0);
  const abort = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      generation.current++;
      abort.current?.abort();
    },
    [],
  );

  async function launch() {
    if (!signedIn) {
      signIn();
      return;
    }
    const run = ++generation.current;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setState('starting');
    setError('');
    setUrl('');
    setLoaded(false);
    try {
      let status = await api<Session>('/notebook-session', {
        method: 'POST',
        signal: controller.signal,
      });
      const deadline = Date.now() + 240_000;
      while (status.state !== 'ready') {
        if (run !== generation.current) return;
        if (status.state === 'stopped')
          throw new Error('The notebook server stopped during startup. Please retry.');
        if (status.state === 'stopping')
          throw new Error('Your notebook server is stopping. Wait a few seconds and retry.');
        if (Date.now() > deadline)
          throw new Error(
            'Startup is taking longer than expected. Retry to reconnect, or check JupyterHub logs.',
          );
        await new Promise((resolve) => setTimeout(resolve, 1500));
        if (run !== generation.current) return;
        status = await api<Session>('/notebook-session', { signal: controller.signal });
      }
      const result = await api<{ url: string }>(`/notebooks/${notebookId}/open`, {
        method: 'POST',
        signal: controller.signal,
      });
      if (run !== generation.current) return;
      setUrl(result.url);
      setState('ready');
    } catch (e) {
      if (run !== generation.current) return;
      setError((e as Error).message);
      setState('error');
    }
  }

  async function stop() {
    setState('stopping');
    setError('');
    try {
      let status = await api<Session>('/notebook-session', { method: 'DELETE' });
      const deadline = Date.now() + 60_000;
      while (status.state === 'stopping') {
        if (Date.now() > deadline)
          throw new Error(
            'The server is still stopping. Reopen this notebook to check its status.',
          );
        await new Promise((resolve) => setTimeout(resolve, 1000));
        status = await api<Session>('/notebook-session');
      }
      setUrl('');
      setLoaded(false);
      setState('idle');
    } catch (e) {
      setError((e as Error).message);
      setState(url ? 'ready' : 'error');
    }
  }

  const editable = connected && Boolean(status) && state === 'ready';
  const kernelBusy = status?.kernel === 'busy';
  return (
    <section
      className={`notebook-workspace studio ${dark ? 'studio-dark' : ''}`}
      aria-label="JupyterLab workspace"
    >
      <div className="studio-topbar">
        <div className="studio-identity">
          <span className="python-badge">
            <Code2 size={19} />
          </span>
          <div>
            <strong>Python notebook</strong>
            <span>Private working copy · JupyterHub</span>
          </div>
        </div>
        <div className="studio-session">
          <span
            className={`kernel-dot ${kernelBusy ? 'busy' : state === 'ready' ? 'online' : ''}`}
          />
          <span role="status">
            {state === 'ready'
              ? `Python 3 · ${status?.kernel || 'connecting'}`
              : state === 'starting'
                ? 'Starting server…'
                : state === 'stopping'
                  ? 'Stopping server…'
                  : 'Session offline'}
          </span>
        </div>
        <div className="studio-actions">
          {(state === 'idle' || state === 'error') && (
            <button className="button" onClick={launch}>
              <Play size={15} />
              {state === 'error' ? 'Retry JupyterLab' : 'Open in JupyterLab'}
            </button>
          )}
          {(state === 'starting' || state === 'stopping') && (
            <LoaderCircle className="spin" size={18} aria-label="Please wait" />
          )}
          {url && (
            <>
              <button className="studio-save" disabled={!editable} onClick={save}>
                <Save size={15} />
                Save
              </button>
              <a
                className="icon-button"
                href={`/api/notebooks/${notebookId}/working-copy`}
                title="Download saved working copy"
                aria-label="Download working copy"
              >
                <Download size={17} />
              </a>
              <a
                className="icon-button"
                href={url}
                target="_blank"
                rel="noreferrer"
                aria-label="Open JupyterLab in a new tab"
              >
                <ExternalLink size={16} />
              </a>
              <button className="studio-stop" onClick={stop} disabled={state === 'stopping'}>
                <Square size={13} />
                Stop server
              </button>
            </>
          )}
        </div>
      </div>
      {url && (
        <div className="studio-commandbar" aria-label="Notebook commands">
          <div className="command-group">
            <button
              className="run-cell"
              disabled={!editable}
              onClick={() => command('notebook:run-cell-and-select-next')}
              title="Run selected cell (Shift+Enter)"
            >
              <Play size={14} fill="currentColor" />
              Run cell
            </button>
            <button
              disabled={!editable || kernelBusy}
              onClick={() => command('notebook:run-all-cells')}
            >
              <Play size={14} />
              Run all
            </button>
            <button
              disabled={!editable}
              onClick={() => command('notebook:interrupt-kernel')}
              title="Interrupt the current computation"
            >
              <Square size={13} />
              Interrupt
            </button>
            <button
              disabled={!editable}
              onClick={() => command('notebook:restart-kernel')}
              title="Restart the Python kernel"
            >
              <RotateCcw size={14} />
              Restart
            </button>
          </div>
          <div className="command-group">
            <button disabled={!editable} onClick={() => addCell(false)}>
              <Code2 size={15} />
              Code
            </button>
            <button disabled={!editable} onClick={() => addCell(true)}>
              <FileText size={15} />
              Markdown
            </button>
          </div>
          <div className="command-group layout-commands">
            <button disabled={!connected} aria-pressed={files} onClick={toggleFiles}>
              <FolderOpen size={15} />
              Files
            </button>
            <button disabled={!connected} onClick={() => command('toc:show-panel')}>
              <ListTree size={15} />
              Outline
            </button>
            <button disabled={!connected} aria-pressed={!focus} onClick={toggleFocus}>
              <PanelLeftClose size={15} />
              {focus ? 'Full IDE' : 'Focus view'}
            </button>
            <button
              disabled={!connected}
              aria-label={dark ? 'Use light theme' : 'Use dark theme'}
              onClick={toggleTheme}
            >
              {dark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              aria-label="Keyboard shortcuts"
              aria-expanded={shortcuts}
              onClick={() => setShortcuts(!shortcuts)}
            >
              <Keyboard size={16} />
            </button>
          </div>
        </div>
      )}
      {shortcuts && (
        <div className="studio-shortcuts">
          <span>
            <kbd>Shift</kbd> + <kbd>Enter</kbd> Run cell
          </span>
          <span>
            <kbd>Ctrl / ⌘</kbd> + <kbd>S</kbd> Save
          </span>
          <span>
            <kbd>Esc</kbd> then <kbd>A / B</kbd> Insert above / below
          </span>
          <span>
            <kbd>Esc</kbd> then <kbd>M / Y</kbd> Markdown / code
          </span>
          <span>Double-click rendered Markdown to edit</span>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {bridgeError && (
        <p className="info" role="status">
          {bridgeError}
        </p>
      )}
      {!url && (
        <div className="studio-welcome">
          <div className="welcome-code">
            <Code2 size={36} />
          </div>
          <span className="eyebrow">YOUR NEXT EXPERIMENT STARTS HERE</span>
          <h3>
            {state === 'starting'
              ? 'Getting your workspace ready'
              : 'Think in cells. Discover in code.'}
          </h3>
          <p>
            {state === 'starting'
              ? 'Starting your personal Python environment and restoring your files. This can take a few minutes on the first launch.'
              : 'A focused notebook for code, explanations, and results. Run Python, explore tables, and bring your ideas to life.'}
          </p>
          <div className="studio-features">
            <span>
              <Code2 size={18} />
              Python + scientific libraries
            </span>
            <span>
              <FileText size={18} />
              Markdown & rich outputs
            </span>
            <span>
              <Save size={18} />
              Persistent working files
            </span>
          </div>
          <small>Open in JupyterLab above to begin. Your community template stays unchanged.</small>
        </div>
      )}
      {url && (
        <div className="studio-canvas">
          {!loaded && (
            <div className="studio-loading" role="status">
              <LoaderCircle className="spin" size={21} />
              Opening your notebook…
            </div>
          )}
          <iframe
            ref={iframe}
            key={url}
            className="jupyter-frame"
            title="JupyterLab notebook editor"
            src={url}
            allow="clipboard-read; clipboard-write"
            onLoad={() => setLoaded(true)}
          />
        </div>
      )}
      <div className="studio-statusbar">
        <span>
          {status ? (
            <>
              <span className={`kernel-dot ${kernelBusy ? 'busy' : 'online'}`} />
              {status.cells} cells · Cell {status.activeCell} selected
            </>
          ) : (
            'Python 3 environment'
          )}
        </span>
        <span>
          {status?.dirty ? (
            'Unsaved changes'
          ) : status ? (
            <>
              <Check size={13} />
              {saved ? `Saved at ${saved}` : 'All changes saved'}
            </>
          ) : (
            'Files persist between sessions'
          )}
        </span>
        <span className="status-tip">Shift+Enter to run · Closing keeps your server running</span>
      </div>
    </section>
  );
}
