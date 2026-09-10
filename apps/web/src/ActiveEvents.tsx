import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Layers3, Plus, X } from 'lucide-react';
import { api } from './api';

type Event = { id: number; title: string; status: string; notebook_id: number };
export default function ActiveEvents({
  compact,
  signedIn,
  create,
}: {
  compact: boolean;
  signedIn: boolean;
  create?: (page: 'benchmarks' | 'notebooks') => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    let active = true;
    setLoading(true);
    const refresh = () =>
      (signedIn ? api<Event[]>('/active-events') : Promise.resolve([]))
        .then((rows) => {
          if (active) {
            setEvents(rows);
            setError('');
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open, signedIn]);
  function close() {
    dialog.current?.close();
    setOpen(false);
  }
  return (
    <div className="active-events">
      <button
        className="active-events-trigger"
        aria-label="View Active Events"
        title="View Active Events"
        onClick={() => setOpen(true)}
      >
        <Layers3 size={22} />
        {!compact && <span>View Active Events</span>}
      </button>
      <dialog
        ref={dialog}
        className="active-events-dialog"
        aria-labelledby="active-events-title"
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) close();
        }}
      >
        <button className="active-events-close" aria-label="Close active events" onClick={close}>
          <X size={20} />
        </button>
        <div className="active-events-content">
          <h2 id="active-events-title">
            {loading
              ? 'Loading Active Events'
              : error
                ? 'Active Events'
                : events.length
                  ? 'Active Events'
                  : 'No Active Events'}
          </h2>
          {error ? (
            <p role="alert">{error}</p>
          ) : events.length ? (
            <ul>
              {events.map((event) => (
                <li key={event.id}>
                  <strong>{event.title}</strong>
                  <span>
                    {event.status === 'queued' ? 'Queued for evaluation' : 'Running and evaluating'}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p>
              Keep track of notebook competition submissions here. Running and queued evaluations
              appear automatically.
            </p>
          )}
          {create && (
            <div className="active-events-actions">
              <button
                onClick={() => {
                  close();
                  create('benchmarks');
                }}
              >
                <Plus size={20} />
                New Benchmark Task
              </button>
              <button
                onClick={() => {
                  close();
                  create('notebooks');
                }}
              >
                <Plus size={20} />
                New Notebook
              </button>
            </div>
          )}
        </div>
        <button className="active-events-footer" onClick={close}>
          <Layers3 size={24} />
          <span>
            {loading ? 'Loading…' : error ? 'Events unavailable' : `${events.length} Active Events`}
          </span>
          <ChevronDown size={22} />
        </button>
      </dialog>
    </div>
  );
}
