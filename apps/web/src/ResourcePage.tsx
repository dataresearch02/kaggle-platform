import { useEffect, useState } from 'react';
import { ArrowLeft, Plus, Download, ExternalLink } from 'lucide-react';
import { api, type Item, type User } from './api';
import Markdown from './Markdown';
import DatasetMetadata from './DatasetMetadata';
import ArtifactFiles from './ArtifactFiles';
import ProfilePhoto from './ProfilePhoto';
import NewNotebook from './NewNotebook';

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
  const [item, setItem] = useState<(Item & { input_available?: boolean }) | null>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let active = true;
    setItem(null);
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
  }, [kind, id, user?.id]);
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
              <button className="button secondary" onClick={yourWork}>
                Your Work
              </button>
              <button
                className="button"
                disabled={item.input_available === false}
                onClick={() => (user ? setCreating(true) : signIn())}
              >
                <Plus size={18} /> New notebook
              </button>
            </div>
          </header>
          {item.input_available === false && (
            <p>
              This model is an external reference. Hosted model files are needed to attach it to a
              notebook.
            </p>
          )}
          <Markdown>{item.description || ''}</Markdown>
          {notice && <p role="status">{notice}</p>}
          {kind === 'datasets' ? (
            <>
              <h2>
                Data preview <small>First 10 rows</small>
              </h2>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      {Object.keys(item.preview?.[0] || {}).map((name) => (
                        <th key={name}>{name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {item.preview?.map((row, i) => (
                      <tr key={i}>
                        {Object.entries(row).map(([name, value]) => (
                          <td key={name}>{value}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <a className="button secondary" href={`/api/datasets/${id}/download`}>
                <Download size={17} /> Download CSV
              </a>
              <DatasetMetadata id={id} owner={user?.id === item.owner_id} />
            </>
          ) : (
            <>
              <div className="pill-row">
                <span>{item.framework}</span>
                <span>{item.license}</span>
              </div>
              <ArtifactFiles
                kind="models"
                id={id}
                owner={user?.id === item.owner_id}
                changed={() =>
                  setItem((current) => (current ? { ...current, input_available: true } : current))
                }
              />
              {item.url && (
                <a className="button secondary" href={item.url} target="_blank" rel="noreferrer">
                  <ExternalLink size={17} /> Model reference
                </a>
              )}
            </>
          )}
        </>
      )}
      {creating && (
        <NewNotebook
          inputSource={{ kind: kind === 'datasets' ? 'dataset' : 'model', id }}
          close={() => setCreating(false)}
          saved={() => setNotice('Notebook saved to Your Work.')}
        />
      )}
    </section>
  );
}
