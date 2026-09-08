/** Same-origin adapter to JupyterLab's public application/command API.
 * The scientific image enables LabApp.expose_app_in_browser. No notebook state is duplicated
 * in React: JupyterLab owns cells, kernel messages, outputs, undo, and persistence.
 */
export type NotebookStatus = {
  kernel: string;
  dirty: boolean;
  cells: number;
  activeCell: number;
  path: string;
};
type LabWidget = { isHidden: boolean; hide: () => void; show: () => void };
type NotebookPanel = {
  toolbar?: LabWidget;
  context?: { path: string; model: { dirty: boolean }; save: () => Promise<void> };
  content?: { activeCellIndex: number; model?: { cells: { length: number } } };
  sessionContext?: { kernelDisplayStatus: string };
};
export type LabApp = {
  restored: Promise<void>;
  commands: {
    hasCommand: (id: string) => boolean;
    isEnabled: (id: string, args?: Record<string, unknown>) => boolean;
    execute: (id: string, args?: Record<string, unknown>) => Promise<unknown>;
  };
  shell: {
    mode: string;
    currentWidget: NotebookPanel | null;
    collapseLeft: () => void;
    collapseRight: () => void;
    activateById: (id: string) => void;
    widgets: (area: string) => IterableIterator<LabWidget>;
    fit: () => void;
  };
};
export function getLab(frame: HTMLIFrameElement): LabApp | undefined {
  try {
    return (frame.contentWindow as (Window & { jupyterapp?: LabApp }) | null)?.jupyterapp;
  } catch {
    return undefined;
  }
}
export function notebookStatus(app: LabApp): NotebookStatus | null {
  const panel = app.shell.currentWidget;
  if (!panel?.content?.model || !panel.context) return null;
  return {
    kernel: panel.sessionContext?.kernelDisplayStatus || 'connecting',
    dirty: panel.context.model.dirty,
    cells: panel.content.model.cells.length,
    activeCell: panel.content.activeCellIndex + 1,
    path: panel.context.path,
  };
}
export async function execute(app: LabApp, command: string, args: Record<string, unknown> = {}) {
  const options = { toolbar: true, ...args };
  if (!app.commands.hasCommand(command) || !app.commands.isEnabled(command, options)) {
    throw new Error(
      'Select a notebook cell first. If this command is unavailable, use the Full IDE view.',
    );
  }
  return app.commands.execute(command, options);
}

const focusStyles = `
body.arena-focus { --jp-brand-color1: #186b55; --jp-brand-color2: #328569; --jp-notebook-padding: 28px; }

body.arena-focus .jp-NotebookPanel { border: 0; }
body.arena-focus .jp-Notebook { background: var(--jp-layout-color2); padding: 28px 20px 100px; }
body.arena-focus .jp-Notebook .jp-Cell { max-width: 1100px; margin: 0 auto 20px; padding: 18px 16px 18px 4px; border: 1px solid var(--jp-border-color2); border-radius: 9px; background: var(--jp-layout-color0); box-shadow: 0 2px 5px rgba(0,0,0,.025); }
body.arena-focus .jp-Notebook .jp-Cell.jp-mod-active { border-color: #75aa91; box-shadow: 0 0 0 1px #75aa9130; }
body.arena-focus .jp-InputArea-editor { border: 0; background: transparent; border-radius: 5px; }
body.arena-focus .jp-InputPrompt, body.arena-focus .jp-OutputPrompt { min-width: 48px; font-size: 11px; color: var(--jp-ui-font-color2); }
body.arena-focus .cm-editor { font-size: 14px; line-height: 1.75; }
body.arena-focus .cm-gutters { background: transparent; color: var(--jp-ui-font-color2); border: 0; }
body.arena-focus .jp-OutputArea { margin-top: 14px; }
body.arena-focus .jp-OutputArea-output { overflow-x: auto; max-height: 600px; }
body.arena-focus .jp-RenderedHTMLCommon { font-size: 14px; line-height: 1.8; }
body.arena-focus .jp-RenderedHTMLCommon table { border-collapse: collapse; font-size: 12px; }
body.arena-focus .jp-RenderedHTMLCommon td, body.arena-focus .jp-RenderedHTMLCommon th { padding: 9px 13px; border-bottom: 1px solid var(--jp-border-color2); }
body.arena-focus .jp-MarkdownCell .jp-RenderedHTMLCommon { padding: 0 10px; }
body.arena-focus .jp-Cell .jp-RenderedImage img { max-width: 100%; height: auto; }
@media(max-width:650px) { body.arena-focus .jp-Notebook { padding: 15px 5px 80px; } body.arena-focus .jp-Notebook .jp-Cell { padding-right: 5px; } body.arena-focus .jp-InputPrompt { min-width: 28px; } }
`;
const hiddenChrome = new WeakMap<LabApp, LabWidget[]>();

export function setFocusMode(frame: HTMLIFrameElement, app: LabApp, focus: boolean) {
  const doc = frame.contentDocument;
  if (!doc) return;
  let sheet = doc.getElementById('arena-notebook-styles');
  if (!sheet) {
    sheet = doc.createElement('style');
    sheet.id = 'arena-notebook-styles';
    sheet.textContent = focusStyles;
    doc.head.append(sheet);
  }
  doc.body.classList.toggle('arena-focus', focus);
  if (focus) {
    app.shell.mode = 'single-document';
    app.shell.collapseLeft();
    app.shell.collapseRight();
    const chrome = [...app.shell.widgets('top'), ...app.shell.widgets('bottom')];
    const toolbar = app.shell.currentWidget?.toolbar;
    if (toolbar) chrome.push(toolbar);
    const visible = chrome.filter((widget) => !widget.isHidden);
    visible.forEach((widget) => widget.hide());
    hiddenChrome.set(app, [...(hiddenChrome.get(app) || []), ...visible]);
  } else {
    (hiddenChrome.get(app) || []).forEach((widget) => widget.show());
    hiddenChrome.delete(app);
    app.shell.mode = 'multiple-document';
  }
  app.shell.fit();
  frame.contentWindow?.dispatchEvent(new Event('resize'));
}
