import { useEffect, useState } from 'react';
import { Pause, Play, Trash2 } from 'lucide-react';
import { api, type Accelerator, type ComputeUsage } from './api';
import { InternetOff } from './GpuUsageMeter';

export type NotebookRun = {
  id: number;
  notebook_id: number;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timed_out';
  accelerator: Accelerator;
  internet: boolean;
  trigger: 'manual' | 'schedule';
  schedule_id: number | null;
  version_id: number | null;
  executed_version_id: number | null;
  output_files: number;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  log?: string;
};
type Schedule = {
  id: number;
  frequency: 'daily' | 'weekly' | 'hourly';
  time_utc: string;
  weekday: number;
  interval_hours: number;
  accelerator: Accelerator;
  status: 'active' | 'paused' | 'disabled';
  consecutive_failures: number;
  next_run_at: string | null;
  disabled_reason: string;
  last_run: NotebookRun | null;
};

export const runStatusLabels: Record<NotebookRun['status'], string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
};
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const isActive = (run: NotebookRun) => run.status === 'queued' || run.status === 'running';

export function AcceleratorSelect({
  value,
  onChange,
  gpuAvailable,
  disabled = false,
}: {
  value: Accelerator;
  onChange: (value: Accelerator) => void;
  gpuAvailable: boolean;
  disabled?: boolean;
}) {
  return (
    <label className="accelerator-select">
      Accelerator
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as Accelerator)}
      >
        <option value="cpu">CPU</option>
        <option value="gpu" disabled={!gpuAvailable}>
          GPU{gpuAvailable ? '' : ' (unavailable)'}
        </option>
      </select>
    </label>
  );
}

/** Background Save & Run All history for the latest saved version. */
export function NotebookRuns({
  notebookId,
  usage,
  revision = 0,
}: {
  notebookId: number;
  usage: ComputeUsage | null;
  revision?: number;
}) {
  const [runs, setRuns] = useState<NotebookRun[]>([]);
  const [selected, setSelected] = useState<NotebookRun | null>(null);
  const [accelerator, setAccelerator] = useState<Accelerator>('cpu');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const pending = runs.some(isActive);
  useEffect(() => {
    let active = true;
    api<NotebookRun[]>(`/code/${notebookId}/runs`)
      .then((rows) => {
        if (active) setRuns(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    if (selected)
      api<NotebookRun>(`/code/${notebookId}/runs/${selected.id}`)
        .then((row) => {
          if (active) setSelected(row);
        })
        .catch(() => {});
    return () => {
      active = false;
    };
  }, [notebookId, revision, tick]);
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => setTick((value) => value + 1), 3000);
    return () => clearTimeout(timer);
  }, [pending, tick]);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
      setTick((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="notebook-runs">
      <p className="notebook-panel-note">
        Runs the latest saved version from top to bottom in a fresh, isolated runtime. Success adds
        an executed version with outputs to the history and saves generated files. Use Save Version
        → Save & Run All to save and run in one step.
      </p>
      <InternetOff />
      <div className="notebook-run-controls">
        <AcceleratorSelect
          value={accelerator}
          onChange={setAccelerator}
          gpuAvailable={!!usage?.gpu_available.background}
          disabled={busy}
        />
        <button
          disabled={busy || pending}
          onClick={() =>
            void act(async () => {
              await api(`/code/${notebookId}/runs`, {
                method: 'POST',
                body: JSON.stringify({ accelerator }),
              });
            })
          }
        >
          <Play size={14} /> {pending ? 'Run in progress' : 'Run saved version'}
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {runs.length ? (
        <ul className="notebook-run-list" aria-label="Run history">
          {runs.slice(0, 20).map((run) => (
            <li key={run.id}>
              <div className="notebook-run-row">
                <button
                  className="notebook-run-summary"
                  aria-expanded={selected?.id === run.id}
                  onClick={() =>
                    selected?.id === run.id
                      ? setSelected(null)
                      : void act(async () =>
                          setSelected(
                            await api<NotebookRun>(`/code/${notebookId}/runs/${run.id}`),
                          ),
                        )
                  }
                >
                  <span className={`run-status ${run.status}`}>{runStatusLabels[run.status]}</span>
                  <span>
                    Run {run.id} · {run.accelerator.toUpperCase()}
                    {run.trigger === 'schedule' ? ' · scheduled' : ''}
                  </span>
                  <small>{new Date(run.finished_at || run.created_at).toLocaleString()}</small>
                </button>
                {isActive(run) && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() =>
                      void act(async () => {
                        await api(`/code/${notebookId}/runs/${run.id}/cancel`, { method: 'POST' });
                      })
                    }
                  >
                    Cancel
                  </button>
                )}
              </div>
              {selected?.id === run.id && (
                <div className="notebook-run-detail">
                  {selected.error && <p className="error">{selected.error}</p>}
                  <p>
                    {selected.started_at
                      ? `Started ${new Date(selected.started_at).toLocaleString()}`
                      : 'Waiting for an isolated runtime'}
                    {selected.duration_seconds !== null
                      ? ` · ${Math.round(selected.duration_seconds)} s`
                      : ''}
                    {selected.status === 'succeeded'
                      ? ` · ${selected.output_files} output files · executed version ${selected.executed_version_id} in history`
                      : ''}
                  </p>
                  <pre className="notebook-run-log">{selected.log || 'No output yet.'}</pre>
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No background runs yet.</p>
      )}
    </div>
  );
}

function describe(schedule: Schedule) {
  if (schedule.frequency === 'hourly')
    return `Every ${schedule.interval_hours} hour${schedule.interval_hours === 1 ? '' : 's'}`;
  if (schedule.frequency === 'weekly')
    return `Weekly on ${weekdays[schedule.weekday]} at ${schedule.time_utc} UTC`;
  return `Daily at ${schedule.time_utc} UTC`;
}

export function NotebookSchedules({
  notebookId,
  usage,
}: {
  notebookId: number;
  usage: ComputeUsage | null;
}) {
  const [rows, setRows] = useState<Schedule[]>([]);
  const [frequency, setFrequency] = useState<Schedule['frequency']>('daily');
  const [time, setTime] = useState('06:00');
  const [weekday, setWeekday] = useState(0);
  const [interval, setInterval] = useState(6);
  const [accelerator, setAccelerator] = useState<Accelerator>('cpu');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const path = `/code/${notebookId}/schedules`;
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
      setRows(await api<Schedule[]>(path));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    api<Schedule[]>(path)
      .then((value) => {
        if (active) setRows(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [notebookId]);
  return (
    <div className="notebook-schedules">
      <p className="notebook-panel-note">
        Scheduled runs use the latest saved version, in UTC. A missed time runs once when Arena is
        back. After 3 consecutive failures a schedule is disabled and you are notified.
      </p>
      {rows.map((schedule) => (
        <article className="notebook-schedule" key={schedule.id}>
          <div>
            <strong>{describe(schedule)}</strong>
            <span className={`run-status ${schedule.status}`}>{schedule.status}</span>
          </div>
          <small>
            {schedule.accelerator.toUpperCase()}
            {schedule.next_run_at
              ? ` · next ${new Date(schedule.next_run_at).toLocaleString()}`
              : ''}
            {schedule.last_run
              ? ` · last run ${runStatusLabels[schedule.last_run.status].toLowerCase()}`
              : ''}
            {schedule.consecutive_failures ? ` · ${schedule.consecutive_failures} failed in a row` : ''}
          </small>
          {schedule.disabled_reason && <p className="error">{schedule.disabled_reason}</p>}
          <div className="notebook-schedule-actions">
            {schedule.status === 'active' ? (
              <button
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await api(`${path}/${schedule.id}/pause`, { method: 'POST' });
                  })
                }
              >
                <Pause size={14} /> Pause
              </button>
            ) : (
              <button
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await api(`${path}/${schedule.id}/resume`, { method: 'POST' });
                  })
                }
              >
                <Play size={14} /> Resume
              </button>
            )}
            <button
              disabled={busy}
              aria-label={`Delete schedule: ${describe(schedule)}`}
              onClick={() => {
                if (window.confirm('Delete this schedule? Its run history is kept.'))
                  void act(async () => {
                    await api(`${path}/${schedule.id}`, { method: 'DELETE' });
                  });
              }}
            >
              <Trash2 size={14} /> Delete
            </button>
          </div>
        </article>
      ))}
      <form
        className="notebook-schedule-form"
        onSubmit={(event) => {
          event.preventDefault();
          void act(async () => {
            await api(path, {
              method: 'POST',
              body: JSON.stringify({
                frequency,
                time_utc: time,
                weekday,
                interval_hours: interval,
                accelerator,
              }),
            });
          });
        }}
      >
        <label>
          Repeat
          <select
            value={frequency}
            onChange={(event) => setFrequency(event.target.value as Schedule['frequency'])}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="hourly">Every N hours</option>
          </select>
        </label>
        {frequency === 'weekly' && (
          <label>
            Day
            <select value={weekday} onChange={(event) => setWeekday(Number(event.target.value))}>
              {weekdays.map((day, index) => (
                <option key={day} value={index}>
                  {day}
                </option>
              ))}
            </select>
          </label>
        )}
        {frequency === 'hourly' ? (
          <label>
            Hours between runs
            <input
              type="number"
              min={1}
              max={168}
              required
              value={interval}
              onChange={(event) => setInterval(Number(event.target.value))}
            />
          </label>
        ) : (
          <label>
            Time (UTC)
            <input
              type="time"
              required
              value={time}
              onChange={(event) => setTime(event.target.value)}
            />
          </label>
        )}
        <AcceleratorSelect
          value={accelerator}
          onChange={setAccelerator}
          gpuAvailable={!!usage?.gpu_available.background}
        />
        <button type="submit" disabled={busy}>
          Add schedule
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
