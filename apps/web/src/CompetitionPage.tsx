import DiscussionList from './DiscussionList';
import DiscussionThread from './DiscussionThread';
import Markdown from './Markdown';
import CompetitionTeam from './CompetitionTeam';
import { useEffect, useState } from 'react';
import { ArrowLeft, Trophy, Users, Calendar, Check } from 'lucide-react';
import { api, apiPage, type Item, type User } from './api';
import CodeList from './CodeList';
import CompetitionOverview from './CompetitionOverview';
import CompetitionData from './CompetitionData';
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
] as const;
export type CompetitionTab = (typeof competitionTabs)[number];
type Submission = { id: number; filename: string; score: number; created_at: string };
type LeaderboardRow = NonNullable<Item['leaderboard']>[number];
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
  const [joined, setJoined] = useState(false);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [submissionTotal, setSubmissionTotal] = useState(0);
  const [board, setBoard] = useState<{ items: LeaderboardRow[]; total: number }>({
    items: [],
    total: 0,
  });
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
    setJoined(false);
    setSubmissions([]);
    Promise.all([
      api<Item>(base),
      user ? api<{ joined: boolean }>(`${base}/membership`) : Promise.resolve({ joined: false }),
      user
        ? apiPage<Submission>(`${base}/submissions?limit=${PAGE_SIZE}`)
        : Promise.resolve({ items: [], total: 0 }),
      apiPage<LeaderboardRow>(`${base}/leaderboard?limit=${PAGE_SIZE}`),
    ])
      .then(([competition, member, results, leaders]) => {
        if (alive) {
          setItem(competition);
          setJoined(member.joined);
          setSubmissions(results.items);
          setSubmissionTotal(results.total);
          setBoard(leaders);
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
          `${base}/leaderboard?offset=${board.items.length}&limit=${PAGE_SIZE}`,
        );
        setBoard((old) => ({ items: [...old.items, ...next.items], total: next.total }));
      } else {
        const next = await apiPage<Submission>(
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
  const closed = !!item.deadline && new Date(item.deadline).getTime() <= Date.now();
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
          disabled={busy || joined || closed}
          onClick={() =>
            void act(async () => {
              await api(`${base}/join`, { method: 'POST' });
              setJoined(true);
              setNotice('You joined the competition');
            })
          }
        >
          {joined ? <Check size={17} /> : <Trophy size={17} />}
          {joined ? 'Joined' : closed ? 'Competition closed' : 'Join competition'}
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
          {item.metric} · {item.metric === 'Accuracy' ? 'higher' : 'lower'} is better
        </span>
      </div>
      <nav className="competition-tabs" aria-label="Competition sections">
        {competitionTabs.map((name) => (
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
      {error && (
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
            <h2>Leaderboard</h2>
            {board.items.length ? (
              <>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Participant</th>
                      <th>Best {item.metric}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.items.map((row) => (
                      <tr key={row.username}>
                        <td>#{row.rank}</td>
                        <td>{row.username}</td>
                        <td>{row.score.toFixed(4)}</td>
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
          <CompetitionTeam id={id} user={user} joined={joined} closed={closed} signIn={signIn} />
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
                    setNotice(`Submission scored: ${result.score.toFixed(4)} ${item.metric}`);
                  });
                }}
              >
                <label>
                  Submit predictions
                  <input name="file" type="file" accept=".csv" required />
                </label>
                <button className="button secondary" disabled={busy}>
                  Score submission
                </button>
              </form>
            )}
            {user && (
              <>
                <h3>Your submissions</h3>
                <p className="muted">Includes submissions from your current team.</p>
                {submissions.length ? (
                  <>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>File</th>
                          <th>Submitted</th>
                          <th>{item.metric}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {submissions.map((row) => (
                          <tr key={row.id}>
                            <td>{row.filename}</td>
                            <td>{new Date(row.created_at).toLocaleString()}</td>
                            <td>{row.score.toFixed(4)}</td>
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
        {tab === 'rules' &&
          (item.rules_url ? (
            <>
              <h2>Competition rules</h2>
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
          ) : (
            <>
              <h2>Submission rules</h2>
              <ul className="competition-rules">
                <li>Sign in and join the competition before submitting predictions.</li>
                <li>
                  Submit a UTF-8 CSV with exactly these columns in order:{' '}
                  {(item.submission_columns || ['id', 'prediction']).join(',')}. Include one finite
                  numeric prediction for every required ID, with no missing, duplicate, or extra
                  IDs. Predictions must be between -1e12 and 1e12.
                </li>
                <li>Submission files must be no larger than 1 MB.</li>
                <li>
                  {item.deadline
                    ? `Submissions close at ${new Date(item.deadline).toLocaleString()}.`
                    : 'This practice competition has no deadline.'}
                </li>
                <li>
                  The leaderboard uses each participant’s best {item.metric} score.{' '}
                  {item.metric === 'Accuracy' ? 'Higher' : 'Lower'} is better; equal scores are
                  ordered by username.
                </li>
              </ul>
              <p className="muted">No additional organizer-specific rules have been published.</p>
            </>
          ))}
      </section>
    </article>
  );
}
