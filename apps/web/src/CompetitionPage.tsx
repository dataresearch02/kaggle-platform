import DiscussionList from './DiscussionList';
import DiscussionThread from './DiscussionThread';
import Markdown from './Markdown';
import CompetitionTeam from './CompetitionTeam';
import { useEffect, useState } from 'react';
import { ArrowLeft, Trophy, Users, Calendar, Check, ArrowUpRight } from 'lucide-react';
import { api, type Item, type User } from './api';
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
      user ? api<Submission[]>(`${base}/submissions`) : Promise.resolve([]),
    ])
      .then(([competition, member, results]) => {
        if (alive) {
          setItem(competition);
          setJoined(member.joined);
          setSubmissions(results);
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
          Closes {item.deadline ? new Date(item.deadline).toLocaleString() : '—'}
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
                    <a href={resource.url} target="_blank" rel="noreferrer" className="text-button">
                      View model <ArrowUpRight size={16} />
                    </a>
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
            {item.leaderboard?.length ? (
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
                    {item.leaderboard.map((row) => (
                      <tr key={row.username}>
                        <td>#{row.rank}</td>
                        <td>{row.username}</td>
                        <td>{row.score.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">
                {item.evaluation_available === false
                  ? 'Local scoring is deferred. Kaggle rankings are not reproduced here.'
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
              <h2>Official competition rules</h2>
              <Markdown>{item.rules_content || 'Read the full rules at the source link.'}</Markdown>
              <a
                className="button secondary"
                href={item.rules_url}
                target="_blank"
                rel="noreferrer"
              >
                Read the full rules on Kaggle
              </a>
              <p className="muted">
                Joining in Arena does not enroll you on Kaggle. Local scoring is deferred; the
                original submission format is PassengerId,Survived.
              </p>
            </>
          ) : (
            <>
              <h2>Submission rules</h2>
              <ul className="competition-rules">
                <li>Sign in and join the competition before submitting predictions.</li>
                <li>
                  Submit a UTF-8 CSV with exactly these columns in order: id,prediction. Include one
                  finite numeric prediction for every required ID, with no missing, duplicate, or
                  extra IDs. Predictions must be between -1e12 and 1e12.
                </li>
                <li>Submission files must be no larger than 1 MB.</li>
                <li>
                  Submissions close at{' '}
                  {item.deadline
                    ? new Date(item.deadline).toLocaleString()
                    : 'the competition deadline'}
                  .
                </li>
                <li>
                  The leaderboard uses each participant’s best {item.metric} score. Lower is better;
                  equal scores are ordered by username.
                </li>
              </ul>
              <p className="muted">No additional organizer-specific rules have been published.</p>
            </>
          ))}
      </section>
    </article>
  );
}
