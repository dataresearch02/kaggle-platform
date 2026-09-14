import DiscussionList from './DiscussionList';
import DiscussionThread from './DiscussionThread';
import Markdown from './Markdown';
import CompetitionTeam from './CompetitionTeam';
import { useEffect, useState } from 'react';
import { ArrowLeft, Trophy, Users, Calendar, Check } from 'lucide-react';
import {
  api,
  apiPage,
  formatScore,
  type Item,
  type LeaderboardRow,
  type Membership,
  type SubmissionRow,
  type User,
} from './api';
import CodeList from './CodeList';
import CompetitionOverview from './CompetitionOverview';
import CompetitionData from './CompetitionData';
import CompetitionHost from './CompetitionHost';
import { JoinRulesDialog, MedalBadge, RankChange, RulesSummary } from './CompetitionRules';
import type { WorkItem } from './YourWork';

export const competitionTabs = [
  'overview',
  'data',
  'code',
  'models',
  'discussion',
  'leaderboard',
  'rules',
  'team',
  'submissions',
  'host',
] as const;
export type CompetitionTab = (typeof competitionTabs)[number];
const PAGE_SIZE = 50;
export default function CompetitionPage({
  id,
  tab,
  discussionId,
  setTab,
  user,
  signIn,
  back,
}: {
  id: number;
  tab: CompetitionTab;
  discussionId?: number;
  setTab: (tab: CompetitionTab) => void;
  user: User | null;
  signIn: () => void;
  back: () => void;
}) {
  const [item, setItem] = useState<Item | null>(null);
  const [membership, setMembership] = useState<Membership | null>(null);
  const [submissions, setSubmissions] = useState<SubmissionRow[]>([]);
  const [submissionTotal, setSubmissionTotal] = useState(0);
  const [boardKind, setBoardKind] = useState<'public' | 'private'>('public');
  const [board, setBoard] = useState<{ items: LeaderboardRow[]; total: number }>({
    items: [],
    total: 0,
  });
  const [rulesOpen, setRulesOpen] = useState(false);
  const [resources, setResources] = useState<Item[]>([]);
  const [owned, setOwned] = useState<WorkItem[]>([]);
  const [resourceId, setResourceId] = useState('');
  const [loading, setLoading] = useState(true);
  const [tabLoading, setTabLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const base = `/competitions/${id}`;
  useEffect(() => {
    let alive = true;
    setError('');
    Promise.all([
      api<Item>(base),
      user ? api<Membership>(`${base}/membership`) : Promise.resolve(null),
      user
        ? apiPage<SubmissionRow>(`${base}/submissions?limit=${PAGE_SIZE}`)
        : Promise.resolve({ items: [], total: 0 }),
    ])
      .then(([competition, member, results]) => {
        if (alive) {
          setItem(competition);
          setMembership(member);
          setSubmissions(results.items);
          setSubmissionTotal(results.total);
        }
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id, user?.id, revision]);
  const ended = !!item?.timeline?.ended;
  // Private standings are public after the end; hosts may preview them earlier.
  const privateVisible = ended || !!membership?.can_host;
  const boardView = boardKind === 'private' && privateVisible ? 'private' : 'public';
  useEffect(() => {
    if (ended) setBoardKind('private');
  }, [ended]);
  useEffect(() => {
    let alive = true;
    apiPage<LeaderboardRow>(`${base}/leaderboard?board=${boardView}&limit=${PAGE_SIZE}`)
      .then((rows) => {
        if (alive) setBoard(rows);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [id, boardView, user?.id, revision]);
  useEffect(() => {
    let alive = true;
    setResources([]);
    setOwned([]);
    setResourceId('');
    setTabLoading(true);
    const kind = 'models';
    const request =
      tab === 'models'
        ? Promise.all([
            api<Item[]>(`${base}/resources/${kind}`),
            user ? api<WorkItem[]>('/work') : Promise.resolve([]),
          ]).then(([rows, work]) => {
            if (alive) {
              setResources(rows);
              setOwned(work.filter((row) => row.work_kind === kind));
            }
          })
        : Promise.resolve();
    request
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setTabLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id, tab, user?.id, revision]);
  async function more(kind: 'leaderboard' | 'submissions') {
    setError('');
    try {
      if (kind === 'leaderboard') {
        const next = await apiPage<LeaderboardRow>(
          `${base}/leaderboard?board=${boardView}&offset=${board.items.length}&limit=${PAGE_SIZE}`,
        );
        setBoard((old) => ({ items: [...old.items, ...next.items], total: next.total }));
      } else {
        const next = await apiPage<SubmissionRow>(
          `${base}/submissions?offset=${submissions.length}&limit=${PAGE_SIZE}`,
        );
        setSubmissions((old) => [...old, ...next.items]);
        setSubmissionTotal(next.total);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function act(action: () => Promise<void>) {
    if (!user) {
      signIn();
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
      setRevision((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <p role="status">Loading competition…</p>;
  if (!item)
    return (
      <section className="empty" role="alert">
        <h1>Competition unavailable</h1>
        <p>{error || 'This competition may have been deleted.'}</p>
        <button className="button secondary" onClick={back}>
          Back to competitions
        </button>
      </section>
    );
  const timeline = item.timeline;
  const closed = timeline
    ? timeline.ended
    : !!item.deadline && new Date(item.deadline).getTime() <= Date.now();
  const joined = !!membership?.joined;
  const needsRules = !!membership?.needs_rules_acceptance && !closed;
  const canHost = !!membership?.can_host;
  const entryClosed = !!timeline && !timeline.entry_open;
  const label = item.metric_label || item.metric || 'Score';
  const direction = item.metric_direction === 'higher' ? 'higher' : 'lower';
  const finalLimit = membership?.max_final_submissions ?? item.max_final_submissions ?? 2;
  const finalCount = membership?.final_selected ?? 0;
  const showPrivate = submissions.some((row) => row.private_score !== undefined);
  const remaining = membership?.remaining_submissions_today ?? 0;
  return (
    <article className="competition-page">
      <button className="text-button competition-back" onClick={back}>
        <ArrowLeft size={16} /> All competitions
      </button>
      <header className="competition-hero">
        <div>
          <div className="eyebrow">
            {item.category} · {closed ? 'CLOSED' : 'OPEN COMPETITION'}
          </div>
          <h1>{item.title}</h1>
          <p>Hosted by {item.owner || 'Arena'}</p>
        </div>
        <button
          className="button"
          disabled={busy || closed || (joined && !needsRules) || (!joined && entryClosed)}
          onClick={() => (user ? setRulesOpen(true) : signIn())}
        >
          {joined && !needsRules ? <Check size={17} /> : <Trophy size={17} />}
          {needsRules
            ? 'Review updated rules'
            : joined
              ? 'Joined'
              : closed
                ? 'Competition closed'
                : entryClosed
                  ? 'Entry deadline passed'
                  : 'Join competition'}
        </button>
      </header>
      <div className="competition-facts">
        <span>
          <Trophy size={16} />
          {item.prize || 'Knowledge'}
        </span>
        <span>
          <Users size={16} />
          {item.participants || 0} participants
        </span>
        <span>
          <Calendar size={16} />
          {item.deadline ? `Closes ${new Date(item.deadline).toLocaleString()}` : 'No deadline'}
        </span>
        <span>
          {label} · {direction} is better
        </span>
      </div>
      <nav className="competition-tabs" aria-label="Competition sections">
        {competitionTabs
          .filter((name) => name !== 'host' || canHost)
          .map((name) => (
            <a
              key={name}
              href={`#competitions/${id}/${name}`}
              aria-current={tab === name ? 'page' : undefined}
              onClick={(event) => {
                event.preventDefault();
                setTab(name);
              }}
            >
              {name === 'code' ? 'Code' : name[0].toUpperCase() + name.slice(1)}
            </a>
          ))}
      </nav>
      {needsRules && (
        <div className="competition-warning" role="alert">
          <span>
            The host updated the rules (revision {membership?.rules_revision}). Accept them again
            before submitting or committing code.
          </span>
          <button className="button secondary" onClick={() => setRulesOpen(true)}>
            Review rules
          </button>
        </div>
      )}
      {error && !rulesOpen && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="competition-notice" role="status">
          {notice}
        </p>
      )}
      <section className="competition-content" aria-label={`${tab} content`}>
        {tab === 'overview' && (
          <CompetitionOverview
            key={id}
            id={id}
            organizer={!!user && item.owner_id === user.id}
            changed={() => setRevision((value) => value + 1)}
          />
        )}
        {tab === 'data' && (
          <CompetitionData
            key={id}
            id={id}
            access={joined || (!!user && item.owner_id === user.id)}
            organizer={!!user && item.owner_id === user.id}
            signedIn={!!user}
            signIn={signIn}
          />
        )}
        {tab === 'code' && (
          <CodeList
            key={`${id}-${user?.id}`}
            competitionId={id}
            user={user}
            signIn={signIn}
            joined={joined}
          />
        )}
        {tab === 'models' && (
          <>
            <h2>Competition models</h2>
            <p>Community model cards shared specifically with this competition.</p>
            {user ? (
              <form
                className="competition-share"
                onSubmit={(event) => {
                  event.preventDefault();
                  void act(async () => {
                    await api(`${base}/resources/models/${resourceId}`, { method: 'POST' });
                    setNotice('Shared with this competition');
                  });
                }}
              >
                <label>
                  Your model cards
                  <select
                    value={resourceId}
                    required
                    onChange={(event) => setResourceId(event.target.value)}
                  >
                    <option value="">Choose your published work</option>
                    {owned
                      .filter((row) => !resources.some((resource) => resource.id === row.id))
                      .map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.title}
                        </option>
                      ))}
                  </select>
                </label>
                <button className="button secondary" disabled={busy || !resourceId}>
                  Share with competition
                </button>
              </form>
            ) : (
              <button className="button secondary" onClick={signIn}>
                Sign in to share your work
              </button>
            )}
            {tabLoading ? (
              <p role="status">Loading shared work…</p>
            ) : resources.length ? (
              <div className="competition-resource-list">
                {resources.map((resource) => (
                  <article key={resource.id}>
                    <h3>{resource.title}</h3>
                    <small>By {resource.owner}</small>
                    <p>{resource.description}</p>
                    {resource.url && (
                      <p className="external-reference">
                        External reference (not available offline):{' '}
                        <a href={resource.url} target="_blank" rel="noreferrer noopener">
                          {resource.url}
                        </a>
                      </p>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty">
                <h3>No models shared yet</h3>
                <p>Publish your work in Data Hub, then share it here.</p>
              </div>
            )}
          </>
        )}
        {tab === 'discussion' &&
          (discussionId ? (
            <DiscussionThread
              key={discussionId}
              id={discussionId}
              competitionId={id}
              user={user}
              signIn={signIn}
            />
          ) : (
            <DiscussionList competitionId={id} user={user} signIn={signIn} />
          ))}
        {tab === 'leaderboard' && (
          <>
            <div className="metadata-heading">
              <h2>Leaderboard</h2>
              <div className="segmented" role="group" aria-label="Leaderboard">
                <button
                  aria-pressed={boardView === 'public'}
                  onClick={() => setBoardKind('public')}
                >
                  Public
                </button>
                <button
                  aria-pressed={boardView === 'private'}
                  disabled={!privateVisible}
                  title={privateVisible ? undefined : 'Published when the competition ends'}
                  onClick={() => setBoardKind('private')}
                >
                  {ended ? 'Private (final)' : 'Private'}
                </button>
              </div>
            </div>
            <p className="muted">
              {boardView === 'public'
                ? item.leaderboard_split
                  ? 'Best scores on the public test rows. Final standings use the private rows and are published when the competition ends.'
                  : 'Best scores on every test row.'
                : ended
                  ? `Final standings from each entry's selected submissions${item.finalized_at ? ', with medals' : ''}. Change compares with the public rank.`
                  : 'Host preview: participants see the private leaderboard after the competition ends.'}
            </p>
            {board.items.length ? (
              <>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Rank</th>
                        <th>Participant</th>
                        <th>
                          {boardView === 'private' ? 'Private' : 'Best'} {label}
                        </th>
                        {boardView === 'private' && (
                          <>
                            <th>Change</th>
                            <th>Medal</th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {board.items.map((row) => (
                        <tr key={`${row.team_id ?? ''}-${row.username}`}>
                          <td>#{row.rank}</td>
                          <td>{row.username}</td>
                          <td>{formatScore(row.score)}</td>
                          {boardView === 'private' && (
                            <>
                              <td>
                                <RankChange rank={row.rank} publicRank={row.public_rank} />
                              </td>
                              <td>
                                <MedalBadge medal={row.medal} />
                              </td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {board.items.length < board.total && (
                  <div className="load-more-row">
                    <span className="muted">
                      Showing {board.items.length} of {board.total}
                    </span>
                    <button className="button secondary" onClick={() => void more('leaderboard')}>
                      Load more
                    </button>
                  </div>
                )}
              </>
            ) : (
              <p className="muted">
                {item.evaluation_available === false
                  ? 'Local scoring is deferred. Rankings from the original host are not reproduced here.'
                  : 'No submissions yet. Set the first baseline.'}
              </p>
            )}
          </>
        )}
        {tab === 'team' && (
          <CompetitionTeam
            id={id}
            user={user}
            joined={joined}
            closed={!!timeline && !timeline.team_forming_open}
            leavingClosed={!!timeline && !timeline.team_changes_open}
            signIn={signIn}
          />
        )}
        {tab === 'submissions' && (
          <>
            <h2>Submissions</h2>
            {item.evaluation_available === false ? (
              <p role="status">
                Local scoring is unavailable because the official test answers were not imported.
                Download the original submission example from Data. You can explore, fork, edit, and
                save code in Arena.
              </p>
            ) : !user ? (
              <button className="button secondary" onClick={signIn}>
                Sign in to submit predictions
              </button>
            ) : !joined ? (
              <p>Join this competition to submit predictions.</p>
            ) : closed ? (
              <p>Submissions are closed.</p>
            ) : timeline && !timeline.started && timeline.starts_at ? (
              <p>Submissions open {new Date(timeline.starts_at).toLocaleString()}.</p>
            ) : needsRules ? (
              <p>Accept the updated rules to submit predictions.</p>
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const body = new FormData(event.currentTarget);
                  void act(async () => {
                    const result = await api<{ score: number }>(`${base}/submissions`, {
                      method: 'POST',
                      body,
                    });
                    setNotice(
                      `Submission scored: ${item.leaderboard_split ? 'public ' : ''}${label} ${formatScore(result.score)}`,
                    );
                  });
                }}
              >
                <p className="submission-allowance" role="status">
                  {remaining} of {membership?.max_daily_submissions} submissions left today
                  {membership?.team_id ? ' for your team' : ''} (resets at 00:00 UTC; notebook
                  commits count too)
                </p>
                <label>
                  Submit predictions
                  <input name="file" type="file" accept=".csv" required />
                </label>
                <button className="button secondary" disabled={busy || remaining === 0}>
                  Score submission
                </button>
              </form>
            )}
            {user && (
              <>
                <h3>Your submissions</h3>
                <p className="muted">
                  Includes submissions from your current team.{' '}
                  {closed
                    ? 'Final selections are locked.'
                    : `Select up to ${finalLimit} final submissions for private scoring (${finalCount} selected, shared with your team). Without a selection, your best public submissions are used.`}
                </p>
                {submissions.length ? (
                  <>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Final</th>
                            <th>File</th>
                            <th>By</th>
                            <th>Submitted</th>
                            <th>
                              {item.leaderboard_split ? 'Public ' : ''}
                              {label}
                            </th>
                            {showPrivate && <th>Private {label}</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {submissions.map((row) => (
                            <tr key={row.id}>
                              <td>
                                <input
                                  type="checkbox"
                                  aria-label={`Use ${row.filename} from ${new Date(row.created_at).toLocaleString()} as a final submission`}
                                  checked={row.final_selected}
                                  disabled={
                                    busy ||
                                    closed ||
                                    (!row.final_selected && finalCount >= finalLimit)
                                  }
                                  onChange={(event) => {
                                    const selected = event.target.checked;
                                    void act(async () => {
                                      await api(`${base}/submissions/${row.id}/final`, {
                                        method: 'PUT',
                                        body: JSON.stringify({ selected }),
                                      });
                                    });
                                  }}
                                />
                              </td>
                              <td>{row.filename}</td>
                              <td>{row.submitter}</td>
                              <td>{new Date(row.created_at).toLocaleString()}</td>
                              <td>{formatScore(row.score)}</td>
                              {showPrivate && <td>{formatScore(row.private_score)}</td>}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {submissions.length < submissionTotal && (
                      <div className="load-more-row">
                        <span className="muted">
                          Showing {submissions.length} of {submissionTotal}
                        </span>
                        <button
                          className="button secondary"
                          onClick={() => void more('submissions')}
                        >
                          Load more
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="muted">You have not submitted predictions yet.</p>
                )}
              </>
            )}
          </>
        )}
        {tab === 'rules' && (
          <>
            <h2>Competition rules</h2>
            <p className="muted">
              Revision {item.rules_revision ?? 1}
              {membership?.accepted_rules_revision
                ? ` · You accepted revision ${membership.accepted_rules_revision}${membership.rules_accepted_at ? ` on ${new Date(membership.rules_accepted_at).toLocaleDateString()}` : ''}`
                : ''}
            </p>
            {item.rules && <Markdown>{item.rules}</Markdown>}
            {item.rules_url && (
              <>
                <h3>Imported rules</h3>
                <Markdown>
                  {item.rules_content || 'The rules text was not included in this import.'}
                </Markdown>
                <p className="external-reference">
                  Original rules (external reference, not available offline):{' '}
                  <a href={item.rules_url} target="_blank" rel="noreferrer noopener">
                    {item.rules_url}
                  </a>
                </p>
                {item.source_url && (
                  <p className="external-reference">
                    Source (external reference, not available offline):{' '}
                    <a href={item.source_url} target="_blank" rel="noreferrer noopener">
                      {item.source_url}
                    </a>
                  </p>
                )}
                <p className="muted">
                  Joining in Arena does not enroll you with the original host. Local scoring is
                  deferred; the original submission format is{' '}
                  {(item.submission_columns || ['id', 'prediction']).join(',')}.
                </p>
              </>
            )}
            <h3>Enforced by Arena</h3>
            <RulesSummary item={item} />
            {!item.rules && !item.rules_url && (
              <p className="muted">No additional host rules have been published.</p>
            )}
          </>
        )}
        {tab === 'host' &&
          (canHost ? (
            <CompetitionHost id={id} changed={() => setRevision((value) => value + 1)} />
          ) : (
            <p>Host tools are available to the competition host and administrators.</p>
          ))}
      </section>
      {rulesOpen && (
        <JoinRulesDialog
          item={item}
          rejoin={joined}
          busy={busy}
          error={error}
          accept={(rulesRevision) =>
            void act(async () => {
              await api(`${base}/join`, {
                method: 'POST',
                body: JSON.stringify({ accept_rules: true, rules_revision: rulesRevision }),
              });
              setRulesOpen(false);
              setNotice(joined ? 'You accepted the updated rules' : 'You joined the competition');
            })
          }
          close={() => {
            setRulesOpen(false);
            setError('');
          }}
        />
      )}
    </article>
  );
}
