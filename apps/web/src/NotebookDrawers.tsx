import { useEffect, useRef, useState } from 'react';
import { Lock, Users, X } from 'lucide-react';
import { api } from './api';

type Label = { name: string; tags: string[] };
type Version = { id: number; label?: Label | null };
type Sharing = {
  visibility: 'private' | 'public';
  usernames: string[];
  allow_comments: boolean;
  owner: string;
};

export default function NotebookDrawers({
  mode,
  close,
  id,
  competitionId,
  save,
  changed,
}: {
  mode: 'save' | 'share';
  close: () => void;
  id: number;
  competitionId?: number;
  save: (label: Label) => Promise<number | false>;
  changed: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [nextNumber, setNextNumber] = useState(1);
  const [ready, setReady] = useState(false);
  const [selected, setSelected] = useState('new');
  const [name, setName] = useState('Version 1');
  const [tags, setTags] = useState('');
  const [type, setType] = useState('save');
  const [filename, setFilename] = useState('submission.csv');
  const [canCommit, setCanCommit] = useState(false);
  const [sharing, setSharing] = useState<Sharing>({
    visibility: 'private',
    usernames: [],
    allow_comments: true,
    owner: '',
  });
  const [username, setUsername] = useState('');
  const [groups, setGroups] = useState<
    { id: number; name: string; members: { username: string }[] }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    async function load() {
      try {
        if (mode === 'save' && id > 0) {
          const [rows, count] = await Promise.all([
            api<Version[]>(`/code/${id}/versions`),
            api<{ count: number }>(`/code/${id}/versions/count`),
          ]);
          if (!active) return;
          setVersions(rows);
          setName(`Version ${count.count + 1}`);
          setNextNumber(count.count + 1);
        } else if (mode === 'share') {
          const [settings, memberGroups] = await Promise.all([
            api<Sharing>(`/code/${id}/share-settings`),
            api<typeof groups>('/account/groups'),
          ]);
          if (active) {
            setSharing(settings);
            setGroups(memberGroups);
          }
        }
        if (mode === 'save' && competitionId) {
          const competition = await api<{ evaluation_available: boolean }>(
            `/competitions/${competitionId}`,
          );
          if (active) setCanCommit(competition.evaluation_available !== false);
        }
        if (active) setReady(true);
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [id, mode, competitionId]);
  function add(names: string[]) {
    setSharing((old) => ({
      ...old,
      usernames: [...new Set([...old.usernames, ...names.filter((value) => value !== old.owner)])],
    }));
  }
  return (
    <dialog
      ref={dialog}
      className="notebook-settings-drawer"
      aria-label={mode === 'save' ? 'Save version' : 'Share notebook'}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) close();
      }}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError('');
          try {
            if (mode === 'share') {
              await api(`/code/${id}/share-settings`, {
                method: 'PUT',
                body: JSON.stringify(sharing),
              });
            } else {
              const label = {
                name: name.trim(),
                tags: tags
                  .split(',')
                  .map((tag) => tag.trim())
                  .filter(Boolean),
              };
              if (
                !label.name ||
                label.tags.length > 10 ||
                label.tags.some((tag) => tag.length > 30)
              )
                throw new Error('Enter a version name and at most 10 tags of 30 characters each.');
              if (selected !== 'new') {
                await api(`/code/${id}/versions/${selected}`, {
                  method: 'PATCH',
                  body: JSON.stringify(label),
                });
              } else {
                const savedId = await save(label);
                if (!savedId)
                  throw new Error(
                    'The notebook could not be saved. Check the editor error and try again.',
                  );
                if (type === 'commit')
                  await api(`/code/${savedId}/commits`, {
                    method: 'POST',
                    body: JSON.stringify({
                      competition_id: competitionId,
                      output_filename: filename,
                    }),
                  });
              }
            }
            changed();
            close();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <header>
          <button type="button" aria-label="Close panel" disabled={busy} onClick={close}>
            <X size={24} />
          </button>
          <h2>{mode === 'save' ? 'Save version' : 'Share'}</h2>
        </header>
        <div className="notebook-drawer-body">
          {loading && <p role="status">Loading…</p>}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <fieldset disabled={loading || busy || !ready}>
            {mode === 'save' ? (
              <>
                <label>
                  Version
                  <select
                    aria-label="Version"
                    value={selected}
                    onChange={(event) => {
                      const value = event.target.value;
                      setSelected(value);
                      const version = versions.find((row) => String(row.id) === value);
                      setName(
                        version?.label?.name ||
                          (version ? `Version ${version.id}` : `Version ${nextNumber}`),
                      );
                      setTags(version?.label?.tags.join(', ') || '');
                    }}
                  >
                    <option value="new">Create a new version</option>
                    {versions.map((version) => (
                      <option key={version.id} value={version.id}>
                        {version.label?.name || `Version ${version.id}`}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Version name
                  <input
                    required
                    maxLength={50}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <span className="notebook-field-count">{name.length} / 50</span>
                <label>
                  Version tags
                  <input
                    value={tags}
                    onChange={(event) => setTags(event.target.value)}
                    placeholder="baseline, feature-engineering"
                  />
                </label>
                <p className="muted">Separate tags with commas. Up to 10 tags.</p>
                {selected === 'new' ? (
                  <>
                    <label>
                      Version type
                      <select
                        aria-label="Version type"
                        value={type}
                        onChange={(event) => setType(event.target.value)}
                      >
                        <option value="save">Save notebook only</option>
                        <option value="commit" disabled={!canCommit}>
                          Save & Run All (Commit)
                        </option>
                      </select>
                    </label>
                    <p>
                      {type === 'save'
                        ? 'Save your cells and current outputs without running the notebook.'
                        : 'Run a fresh saved snapshot in an isolated runtime job, evaluate it, and publish to the competition after success.'}
                    </p>
                    {!canCommit && (
                      <p className="muted">
                        {competitionId
                          ? 'Commit is unavailable because this competition has no local evaluation answers.'
                          : 'Competition commits require a notebook linked to a competition.'}
                      </p>
                    )}
                    {type === 'commit' && (
                      <details>
                        <summary>Advanced settings</summary>
                        <label>
                          Submission filename
                          <input
                            required
                            pattern="[A-Za-z0-9][A-Za-z0-9_.-]*\.csv"
                            value={filename}
                            onChange={(event) => setFilename(event.target.value)}
                          />
                        </label>
                        <p>
                          Join the competition first and write the prediction CSV from your
                          notebook.
                        </p>
                      </details>
                    )}
                  </>
                ) : (
                  <p>
                    Only this version’s name and tags will change. Its cells and outputs stay
                    intact.
                  </p>
                )}
              </>
            ) : (
              <>
                <div className="notebook-visibility-options">
                  {(['private', 'public'] as const).map((value) => (
                    <label key={value} className={sharing.visibility === value ? 'selected' : ''}>
                      <input
                        type="radio"
                        name="visibility"
                        checked={sharing.visibility === value}
                        onChange={() => setSharing({ ...sharing, visibility: value })}
                      />
                      {value === 'private' ? <Lock size={40} /> : <Users size={40} />}
                      <strong>{value === 'private' ? 'Private' : 'Public'}</strong>
                      <span>
                        {value === 'private'
                          ? 'Only you and invited viewers can see this notebook.'
                          : 'Anyone can find and view the published snapshot.'}
                      </span>
                    </label>
                  ))}
                </div>
                <label>
                  Share with people
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="Enter an Arena username"
                  />
                </label>
                <button
                  type="button"
                  className="button secondary"
                  disabled={!username.trim()}
                  onClick={() => {
                    add([username.trim()]);
                    setUsername('');
                  }}
                >
                  Add viewer
                </button>
                {groups.length > 0 && (
                  <label>
                    Add current group members
                    <select
                      defaultValue=""
                      onChange={(event) => {
                        const group = groups.find((row) => row.id === Number(event.target.value));
                        if (group) add(group.members.map((member) => member.username));
                        event.target.value = '';
                      }}
                    >
                      <option value="">Select a group</option>
                      {groups.map((group) => (
                        <option key={group.id} value={group.id}>
                          {group.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <p className="muted">
                  Invited viewers can read and fork. Group selection adds its current members;
                  future membership changes do not change these invitations.
                </p>
                <div className="notebook-permission-row">
                  <strong>{sharing.owner}</strong>
                  <span>Owner</span>
                </div>
                {sharing.usernames.map((value) => (
                  <div key={value} className="notebook-permission-row">
                    <span>{value}</span>
                    <span>Viewer</span>
                    <button
                      type="button"
                      aria-label={`Remove ${value}`}
                      onClick={() =>
                        setSharing({
                          ...sharing,
                          usernames: sharing.usernames.filter((name) => name !== value),
                        })
                      }
                    >
                      <X size={18} />
                    </button>
                  </div>
                ))}
                <label className="notebook-comments-toggle">
                  <input
                    type="checkbox"
                    checked={sharing.allow_comments}
                    onChange={(event) =>
                      setSharing({ ...sharing, allow_comments: event.target.checked })
                    }
                  />
                  Allow comments
                </label>
                <p className="muted">
                  Save applies these access settings. Unsaved editor changes are not published.
                </p>
              </>
            )}
          </fieldset>
        </div>
        <footer>
          <button type="button" disabled={busy} onClick={close}>
            Cancel
          </button>
          <button className="button primary" type="submit" disabled={loading || busy || !ready}>
            {busy ? 'Saving…' : selected !== 'new' && mode === 'save' ? 'Save labels' : 'Save'}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
