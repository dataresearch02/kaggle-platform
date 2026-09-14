import Engagement, { type Reply } from './Engagement';
import { useEffect, useState } from 'react';
import { ArrowLeft, Bookmark, Eye, Lock, Pin } from 'lucide-react';
import Markdown from './Markdown';
import DiscussionEditor from './DiscussionEditor';
import DiscussionAvatar from './DiscussionAvatar';
import { api, type User } from './api';
import ModerationActions, { HiddenNotice } from './Moderation';
import { Timestamp, UserLink, VoteButton } from './Community';
import RevisionHistory from './Revisions';
import type { DiscussionScope } from './DiscussionCreate';
export type DiscussionPost = {
  id: number;
  competition_id: number | null;
  scope: DiscussionScope;
  scope_id: number;
  scope_title: string | null;
  url: string;
  owner_id: number;
  title: string;
  body: string;
  owner: string;
  owner_tier?: string | null;
  mentions?: string[];
  hidden?: boolean;
  hidden_reason?: string;
  created_at: string;
  edited_at?: string | null;
  deleted?: boolean;
  pinned: boolean;
  locked: boolean;
  bookmarked: boolean;
  watching: boolean;
  can_pin: boolean;
  can_edit: boolean;
  can_comment: boolean;
  votes: number;
  voted: boolean;
};
type Comment = Reply;

/** Where "back" leads for a topic in each kind of scope. */
export function scopeHref(post: Pick<DiscussionPost, 'scope' | 'scope_id'>) {
  return {
    competition: `#competitions/${post.scope_id}/discussion`,
    forum: `#discussions/forums/${post.scope_id}`,
    dataset: `#datasets/${post.scope_id}`,
    model: `#models/${post.scope_id}`,
  }[post.scope];
}

export default function DiscussionThread({
  id,
  competitionId,
  user,
  signIn,
}: {
  id: number;
  competitionId?: number;
  user: User | null;
  signIn: () => void;
}) {
  const [post, setPost] = useState<DiscussionPost | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [editingTopic, setEditingTopic] = useState(false);
  const [topicDraft, setTopicDraft] = useState({ title: '', body: '' });
  const [editingComment, setEditingComment] = useState<number | null>(null);
  const [commentDraft, setCommentDraft] = useState('');
  const imageCompetition = post?.scope === 'competition' ? post.scope_id : undefined;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setPost(null);
    setError('');
    setComments([]);
    setNext(null);
    Promise.all([
      api<DiscussionPost>(`/competition-discussions/${id}`),
      api<{ items: Comment[]; next_cursor: number | null }>(
        `/competition-discussions/${id}/comments`,
      ),
    ])
      .then(([row, thread]) => {
        if (!active) return;
        if (competitionId !== undefined && row.competition_id !== competitionId) {
          setError('Discussion does not belong to this competition.');
          return;
        }
        if (competitionId === undefined && row.scope === 'competition') {
          location.replace(row.url);
          return;
        }
        setPost(row);
        setComments(thread.items);
        setNext(thread.next_cursor);
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
  }, [id, competitionId, user?.id, revision]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function reloadComments() {
    const thread = await api<{ items: Comment[]; next_cursor: number | null }>(
      `/competition-discussions/${id}/comments`,
    );
    setComments(thread.items);
    setNext(thread.next_cursor);
  }
  const back = post ? scopeHref(post) : competitionId ? `#competitions/${competitionId}/discussion` : '#discussions';
  const toggle = (field: 'bookmark' | 'pin' | 'lock' | 'watch', current: boolean) =>
    run(async () => {
      if (!user) {
        signIn();
        return;
      }
      await api(`/competition-discussions/${id}/${field}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !current }),
      });
      const key = { bookmark: 'bookmarked', pin: 'pinned', lock: 'locked', watch: 'watching' }[
        field
      ] as 'bookmarked' | 'pinned' | 'locked' | 'watching';
      setPost((value) =>
        value && {
          ...value,
          [key]: !current,
          ...(field === 'lock' ? { can_comment: current && !value.deleted } : {}),
        },
      );
    });
  return (
    <section className="discussion-detail" aria-label="Discussion details">
      <a className="discussion-back" href={back}>
        <ArrowLeft size={18} />{' '}
        {post && post.scope !== 'competition' && post.scope_title
          ? `Back to ${post.scope_title}`
          : 'All discussions'}
      </a>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && <p role="status">Loading discussion…</p>}
      {post && (
        <>
          <article className="competition-post">
            <header className="discussion-detail-heading">
              <h2>
                {post.title}
                {post.locked && (
                  <span className="topic-state">
                    <Lock size={16} aria-hidden="true" /> Locked
                  </span>
                )}
              </h2>
              <div>
                <button
                  aria-label="Bookmark discussion"
                  aria-pressed={post.bookmarked}
                  disabled={busy}
                  onClick={() => void toggle('bookmark', post.bookmarked)}
                >
                  <Bookmark size={18} />
                </button>
                <button
                  aria-label={post.watching ? 'Stop watching discussion' : 'Watch discussion'}
                  title={
                    post.watching
                      ? 'You are notified about new comments'
                      : 'Get notified about new comments'
                  }
                  aria-pressed={post.watching}
                  disabled={busy}
                  onClick={() => void toggle('watch', post.watching)}
                >
                  <Eye size={18} />
                </button>
                {post.can_pin && (
                  <>
                    <button
                      aria-label={post.pinned ? 'Unpin discussion' : 'Pin discussion'}
                      aria-pressed={post.pinned}
                      disabled={busy}
                      onClick={() => void toggle('pin', post.pinned)}
                    >
                      <Pin size={18} />
                    </button>
                    <button
                      aria-label={post.locked ? 'Unlock discussion' : 'Lock discussion'}
                      aria-pressed={post.locked}
                      disabled={busy}
                      onClick={() => void toggle('lock', post.locked)}
                    >
                      <Lock size={18} />
                    </button>
                  </>
                )}
              </div>
            </header>
            <div className="discussion-author">
              <DiscussionAvatar username={post.owner} />
              <small>
                <UserLink username={post.owner} tier={post.owner_tier} /> ·{' '}
                <Timestamp created={post.created_at} edited={post.edited_at} />
                {post.pinned ? ' · Pinned' : ''}
                {post.scope !== 'competition' && post.scope_title && (
                  <>
                    {' · '}
                    <a href={scopeHref(post)}>{post.scope_title}</a>
                  </>
                )}
              </small>
            </div>
            <HiddenNotice hidden={post.hidden} reason={post.hidden_reason} />
            {post.deleted ? (
              <p className="deleted-placeholder">This topic was deleted by its author.</p>
            ) : editingTopic ? (
              <form
                className="discussion-edit-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(async () => {
                    setPost(
                      await api<DiscussionPost>(`/competition-discussions/${id}`, {
                        method: 'PUT',
                        body: JSON.stringify(topicDraft),
                      }),
                    );
                    setEditingTopic(false);
                  });
                }}
              >
                <label>
                  Title
                  <input
                    required
                    minLength={3}
                    maxLength={160}
                    value={topicDraft.title}
                    onChange={(event) => setTopicDraft({ ...topicDraft, title: event.target.value })}
                  />
                </label>
                <DiscussionEditor
                  label="Edit discussion message"
                  value={topicDraft.body}
                  onChange={(value) => setTopicDraft({ ...topicDraft, body: value })}
                  competitionId={imageCompetition}
                  disabled={busy}
                  onUploadingChange={setUploading}
                />
                <div className="button-row">
                  <button
                    className="button"
                    disabled={
                      busy ||
                      uploading ||
                      topicDraft.title.trim().length < 3 ||
                      topicDraft.body.trim().length < 3
                    }
                  >
                    Save changes
                  </button>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={busy}
                    onClick={() => setEditingTopic(false)}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <Markdown mentions={post.mentions}>{post.body}</Markdown>
            )}
            <div className="comment-actions">
              <VoteButton
                kind="competition-post"
                id={post.id}
                votes={post.votes}
                voted={post.voted}
                ownerId={post.owner_id}
                user={user}
                signIn={signIn}
                label="discussion topic"
                disabled={post.deleted}
              />
              {post.can_edit && !editingTopic && (
                <>
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      setTopicDraft({ title: post.title, body: post.body });
                      setEditingTopic(true);
                    }}
                  >
                    Edit topic
                  </button>
                  <button
                    type="button"
                    className="text-button danger-text"
                    disabled={busy}
                    onClick={() => {
                      if (!window.confirm('Delete this topic? Topics with comments keep a placeholder.'))
                        return;
                      void run(async () => {
                        await api(`/competition-discussions/${id}`, { method: 'DELETE' });
                        if (comments.length) setRevision((value) => value + 1);
                        else location.hash = back.slice(1);
                      });
                    }}
                  >
                    Delete topic
                  </button>
                </>
              )}
              {(post.edited_at || post.deleted) && (
                <RevisionHistory kind="competition-post" id={post.id} user={user} />
              )}
            </div>
            <ModerationActions
              kind="competition-post"
              id={post.id}
              ownerId={post.owner_id}
              hidden={post.hidden}
              user={user}
              signIn={signIn}
              label="discussion topic"
              onChange={(change) => {
                if (change.deleted) location.hash = back.slice(1);
                else setPost({ ...post, hidden: change.hidden, hidden_reason: change.reason });
              }}
            />
            <Engagement
              kind="competition-post"
              id={post.id}
              user={user}
              signIn={signIn}
              allowReply={false}
            />
          </article>
          <section className="discussion-comments" aria-label="Discussion comments">
            <h3>Comments</h3>
            {post.locked && (
              <p className="topic-locked-notice" role="note">
                <Lock size={16} aria-hidden="true" /> This topic is locked. Existing comments stay
                visible, but no new comments or replies can be posted.
              </p>
            )}
            {!post.can_comment ? null : user ? (
              <form
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (busy || uploading || !body.trim()) return;
                  setBusy(true);
                  setError('');
                  try {
                    const comment = await api<Comment>(`/competition-discussions/${id}/comments`, {
                      method: 'POST',
                      body: JSON.stringify({ body }),
                    });
                    setComments((old) => [...old, comment]);
                    setBody('');
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <h3>Post a comment</h3>
                <DiscussionEditor
                  label="Comment message"
                  value={body}
                  onChange={setBody}
                  competitionId={imageCompetition}
                  limit={10000}
                  disabled={busy}
                  onUploadingChange={setUploading}
                />
                <button className="button" disabled={busy || uploading || !body.trim()}>
                  {busy ? 'Posting…' : 'Post comment'}
                </button>
              </form>
            ) : (
              <button className="button secondary" onClick={signIn}>
                Sign in to comment
              </button>
            )}
            {comments.map((comment) => (
              <article className="discussion-comment" key={comment.id}>
                <header>
                  <DiscussionAvatar username={comment.username} />
                  <UserLink username={comment.username} tier={comment.owner_tier} />
                  <Timestamp created={comment.created_at} edited={comment.edited_at} />
                </header>
                {comment.deleted ? (
                  <p className="deleted-placeholder">This comment was deleted by its author.</p>
                ) : editingComment === comment.id ? (
                  <form
                    className="discussion-edit-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void run(async () => {
                        const updated = await api<Comment>(
                          `/engagement/competition-post/${id}/replies/${comment.id}`,
                          { method: 'PUT', body: JSON.stringify({ body: commentDraft }) },
                        );
                        setComments((old) =>
                          old.map((row) => (row.id === updated.id ? updated : row)),
                        );
                        setEditingComment(null);
                      });
                    }}
                  >
                    <DiscussionEditor
                      label="Edit comment"
                      value={commentDraft}
                      onChange={setCommentDraft}
                      competitionId={imageCompetition}
                      limit={10000}
                      disabled={busy}
                      onUploadingChange={setUploading}
                    />
                    <div className="button-row">
                      <button className="button small" disabled={busy || uploading || !commentDraft.trim()}>
                        Save
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        disabled={busy}
                        onClick={() => setEditingComment(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <HiddenNotice hidden={comment.hidden} reason={comment.hidden_reason} />
                    <Markdown mentions={comment.mentions}>{comment.body}</Markdown>
                  </>
                )}
                <div className="comment-actions">
                  <VoteButton
                    kind="reply"
                    id={comment.id}
                    votes={comment.votes}
                    voted={comment.voted}
                    ownerId={comment.owner_id}
                    user={user}
                    signIn={signIn}
                    label={`comment by ${comment.username}`}
                    disabled={comment.deleted}
                  />
                  {user?.id === comment.owner_id && !comment.deleted && (
                    <>
                      <button
                        type="button"
                        className="text-button"
                        disabled={busy}
                        onClick={() => {
                          setCommentDraft(comment.body);
                          setEditingComment(comment.id);
                        }}
                      >
                        Edit comment
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        aria-label={`Delete comment by ${comment.username}`}
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await api(`/engagement/competition-post/${id}/replies/${comment.id}`, {
                              method: 'DELETE',
                            });
                            await reloadComments();
                          })
                        }
                      >
                        Delete comment
                      </button>
                    </>
                  )}
                  {(comment.edited_at || comment.deleted) && (
                    <RevisionHistory kind="reply" id={comment.id} user={user} />
                  )}
                </div>
                <ModerationActions
                  kind="reply"
                  id={comment.id}
                  ownerId={comment.owner_id}
                  hidden={comment.hidden}
                  user={user}
                  signIn={signIn}
                  label={`comment by ${comment.username}`}
                  onChange={(change) =>
                    setComments((old) =>
                      change.deleted
                        ? old.filter((row) => row.id !== comment.id)
                        : old.map((row) =>
                            row.id === comment.id
                              ? { ...row, hidden: change.hidden, hidden_reason: change.reason }
                              : row,
                          ),
                    )
                  }
                />
                <Engagement
                  kind="competition-comment"
                  id={comment.id}
                  competitionId={imageCompetition}
                  canReply={post.can_comment && !comment.deleted}
                  user={user}
                  signIn={signIn}
                />
              </article>
            ))}
            {!comments.length && (
              <p>
                {post.can_comment
                  ? 'No comments yet. Be the first to join the conversation.'
                  : 'No comments.'}
              </p>
            )}
            {next && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const result = await api<{ items: Comment[]; next_cursor: number | null }>(
                      `/competition-discussions/${id}/comments?after=${next}`,
                    );
                    setComments((old) =>
                      [
                        ...old,
                        ...result.items.filter((row) => !old.some((item) => item.id === row.id)),
                      ].sort((a, b) => a.id - b.id),
                    );
                    setNext(result.next_cursor);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Load more comments
              </button>
            )}
          </section>
        </>
      )}
      {!loading && !post && (
        <button className="button secondary" onClick={() => setRevision((v) => v + 1)}>
          Try again
        </button>
      )}
    </section>
  );
}
