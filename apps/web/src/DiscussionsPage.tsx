import { useEffect, useState } from 'react';
import { api, type User } from './api';
import DiscussionList from './DiscussionList';

export default function DiscussionsPage({
  user,
  signIn,
  query,
}: {
  user: User | null;
  signIn: () => void;
  query: string;
}) {
  const [error, setError] = useState('');
  // Keep existing bookmarked global links working; the canonical detail lives in its competition.
  useEffect(() => {
    let active = true;
    const redirect = () => {
      const id = /^#discussions\/(\d+)$/.exec(location.hash)?.[1];
      if (!id) return;
      api<{ competition_id: number }>(`/competition-discussions/${id}`)
        .then((post) => {
          if (active && location.hash === `#discussions/${id}`)
            location.replace(`#competitions/${post.competition_id}/discussion/${id}`);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    };
    redirect();
    window.addEventListener('hashchange', redirect);
    return () => {
      active = false;
      window.removeEventListener('hashchange', redirect);
    };
  }, []);
  return (
    <section className="discussions-page">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <DiscussionList user={user} signIn={signIn} initialQuery={query} />
    </section>
  );
}
