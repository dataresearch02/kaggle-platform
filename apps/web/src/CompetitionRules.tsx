import { useEffect, useRef, useState } from 'react';
import Markdown from './Markdown';
import type { Item, Medal } from './api';

const when = (value?: string | null) => (value ? new Date(value).toLocaleString() : '');

/** Rules Arena enforces for every competition, from its current settings. */
export function RulesSummary({ item, hostRules = false }: { item: Item; hostRules?: boolean }) {
  const text = item.rules || item.rules_content || '';
  const direction = item.metric_direction === 'higher' ? 'Higher' : 'Lower';
  return (
    <>
      {hostRules && text && <Markdown>{text}</Markdown>}
      <ul className="competition-rules">
        <li>Accept these rules and join before submitting predictions or committing notebooks.</li>
        <li>
          Submit a UTF-8 CSV with exactly these columns in order:{' '}
          {(item.submission_columns || ['id', 'prediction']).join(',')}. Include one prediction
          for every required ID, with no missing, duplicate, or extra IDs. Files must be no larger
          than 1 MB.
        </li>
        <li>
          Up to {item.max_daily_submissions ?? 5} submissions per UTC day for each team, or each
          participant without a team, counting CSV uploads and notebook commits. Rejected files do
          not count.
        </li>
        <li>
          Scored with {item.metric_label || item.metric}. {direction} is better.{' '}
          {item.leaderboard_split
            ? 'The public leaderboard uses part of the test rows; final standings use the remaining private rows.'
            : 'Every test row counts toward the public leaderboard and the final standings.'}
        </li>
        <li>
          Select up to {item.max_final_submissions ?? 2} final submissions. Without a selection,
          your best public submissions are used.
        </li>
        {item.deadline ? (
          <>
            {item.timeline?.starts_at && <li>Submissions open {when(item.timeline.starts_at)}.</li>}
            <li>
              {item.entry_deadline
                ? `Join and form teams by ${when(item.entry_deadline)}.`
                : 'Join and form teams until the competition ends.'}
            </li>
            {item.merger_deadline && <li>Team changes close {when(item.merger_deadline)}.</li>}
            <li>
              Submissions close {when(item.deadline)}. Final ranks and medals are published after
              the end.
            </li>
          </>
        ) : (
          <li>This competition has no deadline, so it has no final ranking and awards no medals.</li>
        )}
      </ul>
    </>
  );
}

export function JoinRulesDialog({
  item,
  rejoin,
  busy,
  error,
  accept,
  close,
}: {
  item: Item;
  rejoin: boolean;
  busy: boolean;
  error: string;
  accept: (revision: number) => void;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [accepted, setAccepted] = useState(false);
  useEffect(() => {
    const panel = dialog.current;
    panel?.showModal();
    return () => panel?.close();
  }, []);
  const revision = item.rules_revision ?? 1;
  return (
    <dialog
      ref={dialog}
      className="rules-dialog"
      aria-labelledby="rules-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) close();
      }}
    >
      <h2 id="rules-dialog-title">{rejoin ? 'The rules have changed' : 'Competition rules'}</h2>
      <p className="muted">
        {rejoin
          ? `Revision ${revision}. Accept the updated rules to keep submitting and committing code.`
          : `Revision ${revision}. Read and accept the rules to join ${item.title}.`}
      </p>
      <div className="rules-dialog-body">
        {!(item.rules || item.rules_content) && (
          <p>The host has not published additional rules.</p>
        )}
        <RulesSummary item={item} hostRules />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (accepted) accept(revision);
        }}
      >
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)}
          />
          I have read and accept the competition rules (revision {revision}).
        </label>
        <div className="work-delete-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={close}>
            Cancel
          </button>
          <button className="button" disabled={!accepted || busy}>
            {rejoin ? 'Accept updated rules' : 'Accept and join'}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export function MedalBadge({ medal }: { medal?: Medal | null }) {
  if (!medal) return null;
  return (
    <span className={`medal medal-${medal}`}>{medal[0].toUpperCase() + medal.slice(1)}</span>
  );
}

/** Movement from the public to the final (private) rank. */
export function RankChange({ rank, publicRank }: { rank: number; publicRank?: number | null }) {
  if (publicRank === null || publicRank === undefined) return <span>—</span>;
  const change = publicRank - rank;
  return (
    <span
      className={`rank-change ${change > 0 ? 'up' : change < 0 ? 'down' : ''}`}
      aria-label={change ? `${change > 0 ? 'Up' : 'Down'} ${Math.abs(change)}` : 'No change'}
    >
      {change > 0 ? `▲ ${change}` : change < 0 ? `▼ ${-change}` : '='}
    </span>
  );
}
