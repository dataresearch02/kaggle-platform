import { useEffect, useState } from 'react';
import { ArrowLeft, Archive, MessageSquare } from 'lucide-react';
import { api, type User } from './api';
import DiscussionList from './DiscussionList';
import DiscussionThread from './DiscussionThread';
import type { Forum } from './Community';

/** `#discussions`, `#discussions/forums/<id>` or a topic at `#discussions/<id>`. */
export function discussionRouteFromHash() {
  const forum = /^#discussions\/forums\/(\d+)$/.exec(location.hash)?.[1];
  const topic = /^#discussions\/(\d+)$/.exec(location.hash)?.[1];
  return {
    forumId: forum ? Number(forum) : undefined,
    topicId: topic ? Number(topic) : undefined,
  };
}

export default function DiscussionsPage({
  user,
  signIn,
  query,
}: {
  user: User | null;
  signIn: () => void;
  query: string;
}) {
  const [route, setRoute] = useState(discussionRouteFromHash);
  const [forums, setForums] = useState<Forum[]>([]);
  const [forum, setForum] = useState<Forum | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const change = () => setRoute(discussionRouteFromHash());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => {
    let active = true;
    setError('');
    setForum(null);
    const request =
      route.forumId !== undefined
        ? api<Forum>(`/forums/${route.forumId}`).then((row) => {
            if (active) setForum(row);
          })
        : route.topicId === undefined
          ? api<Forum[]>('/forums').then((rows) => {
              if (active) setForums(rows);
            })
          : Promise.resolve();
    request.catch((e) => {
      if (active) setError(e.message);
    });
    return () => {
      active = false;
    };
  }, [route.forumId, route.topicId, user?.id]);
  if (route.topicId !== undefined)
    return (
      <section className="discussions-page">
        <DiscussionThread key={route.topicId} id={route.topicId} user={user} signIn={signIn} />
      </section>
    );
  return (
    <section className="discussions-page">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {route.forumId !== undefined ? (
        <>
          <a className="discussion-back" href="#discussions">
            <ArrowLeft size={18} /> All forums
          </a>
          {forum && (
            <>
              <header className="forum-heading">
                <div className="eyebrow">FORUM</div>
                <h1>{forum.title}</h1>
                <p>{forum.description}</p>
                {forum.archived && (
                  <p className="topic-locked-notice" role="note">
                    <Archive size={16} aria-hidden="true" /> This forum is archived. Its topics stay
                    readable, but new topics and comments are closed.
                  </p>
                )}
              </header>
              <DiscussionList
                key={forum.id}
                scope="forum"
                scopeId={forum.id}
                scopeTitle={forum.title}
                heading="Topics"
                user={user}
                signIn={signIn}
                initialQuery={query}
              />
            </>
          )}
        </>
      ) : (
        <>
          <section className="forum-grid" aria-label="Forums">
            {forums.map((row) => (
              <a key={row.id} className="forum-card" href={`#discussions/forums/${row.id}`}>
                <h2>{row.title}</h2>
                <p>{row.description}</p>
                <small>
                  <MessageSquare size={14} aria-hidden="true" /> {row.topic_count}{' '}
                  {row.topic_count === 1 ? 'topic' : 'topics'}
                  {row.latest_topic_at &&
                    ` · Latest ${new Date(row.latest_topic_at).toLocaleDateString()}`}
                </small>
              </a>
            ))}
          </section>
          <DiscussionList
            heading="Recent topics across Arena"
            user={user}
            signIn={signIn}
            initialQuery={query}
          />
        </>
      )}
    </section>
  );
}
