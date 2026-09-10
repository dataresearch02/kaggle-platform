import { useEffect, useState } from 'react';
import { api, type User } from './api';

type Team = {
  id: number;
  name: string;
  owner_id: number;
  invite_code: string;
  members: { id: number; username: string; joined_at: string }[];
};

export default function CompetitionTeam({
  id,
  user,
  joined,
  closed,
  signIn,
}: {
  id: number;
  user: User | null;
  joined: boolean;
  closed: boolean;
  signIn: () => void;
}) {
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const base = `/competitions/${id}/team`;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    setTeam(null);
    (user ? api<Team | null>(base) : Promise.resolve(null))
      .then((value) => {
        if (active) setTeam(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id, user?.id]);

  async function change(path: string, body?: object) {
    setBusy(true);
    setError('');
    try {
      const result = await api<Team | null>(base + path, {
        method: body ? 'POST' : 'DELETE',
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      setTeam(result ?? null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="competition-team">
      <h2>Team</h2>
      <p>
        Create a team or join teammates using their invite code. Submission scores and leaderboard
        positions belong to individual participants.
      </p>
      {error && <p role="alert">{error}</p>}
      {loading ? (
        <p role="status">Loading team…</p>
      ) : !user ? (
        <button className="button secondary" onClick={signIn}>
          Sign in to manage your team
        </button>
      ) : team ? (
        <>
          <h3>{team.name}</h3>
          <label>
            Team invite code
            <input
              readOnly
              value={team.invite_code}
              onFocus={(event) => event.currentTarget.select()}
            />
          </label>
          <p className="muted">Share this code with participants you want to invite.</p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {team.members.map((member) => (
                  <tr key={member.id}>
                    <td>{member.username}</td>
                    <td>{member.id === team.owner_id ? 'Captain' : 'Member'}</td>
                    <td>{new Date(member.joined_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {closed ? (
            <p>Team changes are closed.</p>
          ) : (
            <>
              <p className="muted">
                If the captain leaves, the next member becomes captain. Empty teams are deleted.
              </p>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => {
                  if (window.confirm('Leave this team?')) void change('');
                }}
              >
                Leave team
              </button>
            </>
          )}
        </>
      ) : !joined ? (
        <p>Join this competition before creating or joining a team.</p>
      ) : closed ? (
        <p>Team changes are closed.</p>
      ) : (
        <div className="team-forms">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void change('', { name: new FormData(event.currentTarget).get('name') });
            }}
          >
            <h3>Create a team</h3>
            <label>
              Team name
              <input name="name" required maxLength={80} />
            </label>
            <button className="button primary" disabled={busy}>
              Create team
            </button>
          </form>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void change('/join', {
                invite_code: new FormData(event.currentTarget).get('invite_code'),
              });
            }}
          >
            <h3>Join a team</h3>
            <label>
              Invite code
              <input name="invite_code" required maxLength={40} />
            </label>
            <button className="button secondary" disabled={busy}>
              Join team
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
