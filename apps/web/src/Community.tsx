import { useEffect, useState } from 'react';
import { ArrowUp } from 'lucide-react';
import { api, type User } from './api';

/** Content kinds shared by votes, reports and notifications. */
export type VoteKind =
  | 'code'
  | 'dataset'
  | 'model'
  | 'competition-post'
  | 'reply'
  | 'notebook-comment';
export type VoteState = { votes: number; voted: boolean };
export const tierNames = ['Novice', 'Contributor', 'Expert', 'Master', 'Grandmaster'] as const;
export type RankingCategory = 'competitions' | 'datasets' | 'notebooks' | 'discussions';
export const rankingCategories: RankingCategory[] = [
  'competitions',
  'datasets',
  'notebooks',
  'discussions',
];
export const categoryLabels: Record<RankingCategory, string> = {
  competitions: 'Competitions',
  datasets: 'Datasets',
  notebooks: 'Notebooks',
  discussions: 'Discussions',
};
export type Progression = {
  tier: number;
  tier_name: string;
  categories: {
    category: RankingCategory;
    tier: number;
    tier_name: string;
    gold: number;
    silver: number;
    bronze: number;
  }[];
};
export type Forum = {
  id: number;
  slug: string;
  title: string;
  description: string;
  position: number;
  archived: boolean;
  topic_count: number;
  latest_topic_at: string | null;
  can_post: boolean;
  can_moderate: boolean;
};
export type ActivityItem = {
  kind: 'notebook' | 'dataset' | 'model' | 'topic' | 'medal';
  id: number;
  actor: string;
  title: string;
  url: string | null;
  message: string;
  created_at: string;
  detail: { medal?: string; rank?: number; team_count?: number; scope?: string };
};

/** A small tier label next to a username; Novice is not shown in compact form. */
export function TierBadge({ tier, compact = true }: { tier?: string | null; compact?: boolean }) {
  if (!tier || (compact && tier === 'Novice')) return null;
  return (
    <span className={`tier-badge tier-${tier.toLowerCase()}`} title={`${tier} tier`}>
      {tier}
    </span>
  );
}

export function UserLink({ username, tier }: { username: string; tier?: string | null }) {
  return (
    <span className="user-link">
      <a href={`#profile/${encodeURIComponent(username)}`}>{username}</a>
      <TierBadge tier={tier} />
    </span>
  );
}

/** "Posted" time with an "edited" marker when the text changed later. */
export function Timestamp({ created, edited }: { created: string; edited?: string | null }) {
  return (
    <small className="timestamp">
      {new Date(created).toLocaleString()}
      {edited && (
        <span className="edited-marker" title={`Edited ${new Date(edited).toLocaleString()}`}>
          {' '}
          · edited {new Date(edited).toLocaleString()}
        </span>
      )}
    </small>
  );
}

/** Upvote toggle: one vote per user, never on your own content. */
export function VoteButton({
  kind,
  id,
  votes,
  voted,
  ownerId,
  user,
  signIn,
  label,
  disabled = false,
}: {
  kind: VoteKind;
  id: number;
  votes?: number;
  voted?: boolean;
  ownerId?: number;
  user: User | null;
  signIn: () => void;
  label: string;
  disabled?: boolean;
}) {
  const [state, setState] = useState<VoteState>({ votes: votes || 0, voted: !!voted });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setState({ votes: votes || 0, voted: !!voted }), [id, votes, voted]);
  const own = !!user && user.id === ownerId;
  return (
    <span className="vote-control">
      <button
        type="button"
        className="vote-button"
        aria-pressed={state.voted}
        aria-label={`${state.voted ? 'Remove upvote from' : 'Upvote'} ${label}`}
        title={own ? 'You cannot vote on your own content' : state.voted ? 'Remove your upvote' : 'Upvote'}
        disabled={busy || own || disabled}
        onClick={async () => {
          if (!user) {
            signIn();
            return;
          }
          setBusy(true);
          setError('');
          try {
            setState(
              await api<VoteState>(`/votes/${kind}/${id}`, {
                method: state.voted ? 'DELETE' : 'PUT',
              }),
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ArrowUp size={14} aria-hidden="true" />
        {state.votes}
      </button>
      {error && (
        <small role="alert" className="error">
          {error}
        </small>
      )}
    </span>
  );
}

export const medalOrder = ['gold', 'silver', 'bronze'] as const;

export function MedalCounts({ gold, silver, bronze }: { gold: number; silver: number; bronze: number }) {
  const counts = { gold, silver, bronze };
  return (
    <span className="medal-counts">
      {medalOrder.map((medal) => (
        <span key={medal} className={`medal medal-${medal}`} title={`${counts[medal]} ${medal}`}>
          {medal[0].toUpperCase() + medal.slice(1)} {counts[medal]}
        </span>
      ))}
    </span>
  );
}
