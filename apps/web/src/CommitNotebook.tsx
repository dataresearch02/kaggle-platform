import { useEffect, useState } from 'react';
import { api } from './api';

type Commit = {
  id: number;
  status: 'queued' | 'running' | 'failed' | 'succeeded' | 'cancelled';
  error: string | null;
  score: number | null;
  output_filename: string;
};
export default function CommitNotebook({
  notebookId,
  competitionId,
  save,
  disabled,
  close,
  statusOnly = false,
}: {
  statusOnly?: boolean;
  notebookId: number;
  competitionId: number;
  save: () => Promise<boolean>;
  disabled: boolean;
  close?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [evaluationAvailable, setEvaluationAvailable] = useState<boolean | null>(null);
  useEffect(() => {
    let active = true;
    setEvaluationAvailable(null);
    api<{ evaluation_available?: boolean }>(`/competitions/${competitionId}`)
      .then((item) => {
        if (active) setEvaluationAvailable(item.evaluation_available !== false);
      })
      .catch((error) => {
        if (active) setError(error.message);
      });
    return () => {
      active = false;
    };
  }, [competitionId]);
  const [filename, setFilename] = useState('submission.csv');
  const [job, setJob] = useState<Commit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const latest = await api<Commit | null>(`/code/${notebookId}/commits/latest`);
        if (active) {
          setJob(latest);
          setError('');
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
      if (active) timer = setTimeout(refresh, 2000);
    }
    void refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [notebookId]);
  const pending = job?.status === 'queued' || job?.status === 'running';
  return (
    <div className="notebook-commit">
      {!statusOnly && (
        <button
          className="button secondary"
          disabled={disabled || busy || pending || evaluationAvailable !== true}
          onClick={() => setOpen(!open)}
        >
          {evaluationAvailable === false
            ? 'Local scoring unavailable'
            : pending
              ? `Commit ${job.status}…`
              : 'Save & Commit'}
        </button>
      )}
      {job && (
        <span role="status" className="commit-status">
          {job.status === 'succeeded'
            ? `Evaluated · Score ${job.score?.toFixed(5)}`
            : job.status === 'failed'
              ? `Commit failed: ${job.error}`
              : `Commit ${job.status}`}
        </span>
      )}
      {pending && (
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              setJob(
                await api<Commit>(`/code/${notebookId}/commits/${job.id}/cancel`, {
                  method: 'POST',
                }),
              );
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Cancel evaluation
        </button>
      )}
      {job?.status === 'succeeded' && (
        <a href={`#competitions/${competitionId}/code`} onClick={close}>
          Competition code
        </a>
      )}
      {error && <span role="alert">{error}</span>}
      {open && (
        <form
          className="commit-popover"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError('');
            try {
              if (!(await save())) return;
              const result = await api<Commit>(`/code/${notebookId}/commits`, {
                method: 'POST',
                body: JSON.stringify({ competition_id: competitionId, output_filename: filename }),
              });
              setJob(result);
              setOpen(false);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <strong>Run and evaluate in competition</strong>
          <p>
            An isolated runtime job runs your saved cells from top to bottom without network access.
            Read test data from <code>test.csv</code> or <code>os.environ['ARENA_TEST_DATA']</code>.
          </p>
          <label>
            Prediction CSV filename
            <input
              required
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
              pattern="[A-Za-z0-9][A-Za-z0-9_.-]*\.csv"
            />
          </label>
          <p>
            Write this file with columns <code>id,prediction</code>. Arena evaluates it and
            publishes this snapshot in competition Code only after success. Join the competition
            first.
          </p>
          <button
            type="submit"
            disabled={disabled || busy || pending || evaluationAvailable !== true}
          >
            {busy ? 'Saving…' : 'Run and evaluate'}
          </button>
          <button type="button" disabled={busy} onClick={() => setOpen(false)}>
            Cancel
          </button>
        </form>
      )}
    </div>
  );
}
