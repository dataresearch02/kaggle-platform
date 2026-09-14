"""Shared community rules: topic scopes, content visibility, links, mentions and revisions.

Every community surface (feeds, search, votes, notifications, rankings) asks these
helpers whether a user may see an item, so private notebooks and datasets, hidden
content and restricted profiles never leak through a new path.
"""

import re

from fastapi import HTTPException
from sqlalchemy import and_, false, or_, select

from .dataset_access import visible_datasets
from .models import (
    Competition,
    CompetitionPost,
    CompetitionTopicSettings,
    ContentReply,
    ContentRevision,
    Dataset,
    Forum,
    ModelCard,
    Notebook,
    NotebookComment,
    User,
    UserProfile,
    now,
)
from .notebook_visibility import visible_notebooks
from .permissions import can_view, is_admin, not_hidden

SCOPES = ("competition", "forum", "dataset", "model")
# Kinds shared by reports, votes and notifications.
CONTENT_KINDS = (
    "competition-post",
    "reply",
    "code",
    "notebook-comment",
    "dataset",
    "model",
)


def visible_topics(user):
    """SQL filter for topics whose scope and moderation state the user may see."""
    return and_(
        or_(
            CompetitionPost.scope.in_(("competition", "forum")),
            and_(
                CompetitionPost.scope == "dataset",
                CompetitionPost.scope_id.in_(
                    select(Dataset.id).where(visible_datasets(user))
                ),
            ),
            and_(
                CompetitionPost.scope == "model",
                CompetitionPost.scope_id.in_(
                    select(ModelCard.id).where(not_hidden(ModelCard, user))
                ),
            ),
        ),
        not_hidden(CompetitionPost, user),
    )


def public_topics():
    """Topics anyone may see that were not deleted by their author."""
    return and_(visible_topics(None), CompetitionPost.deleted_at.is_(None))


def restricted_profiles(viewer):
    """Users whose profile the viewer may not see: private, or hidden from non-admins."""
    return select(UserProfile.user_id).where(
        or_(
            UserProfile.visibility == "private",
            UserProfile.hidden == 1 if not is_admin(viewer) else false(),
        )
    )


def listed_users(viewer):
    """SQL filter on User for people lists (followers, rankings, search)."""
    return or_(
        User.id.not_in(restricted_profiles(viewer)),
        User.id == (viewer.id if viewer else -1),
    )


def scope_row(db, scope, scope_id):
    model = {
        "competition": Competition,
        "forum": Forum,
        "dataset": Dataset,
        "model": ModelCard,
    }.get(scope)
    return db.get(model, scope_id) if model and scope_id is not None else None


def scope_visible(db, scope, scope_id, user):
    if scope == "dataset":
        return (
            db.scalar(
                select(Dataset.id).where(Dataset.id == scope_id, visible_datasets(user))
            )
            is not None
        )
    if scope == "model":
        row = db.get(ModelCard, scope_id)
        return bool(row and can_view(row, user))
    return scope_row(db, scope, scope_id) is not None


def topic_visible(db, post, user):
    return bool(
        post
        and can_view(post, user)
        and scope_visible(db, post.scope, post.scope_id, user)
    )


def require_topic(db, id, user):
    post = db.get(CompetitionPost, id)
    if not topic_visible(db, post, user):
        raise HTTPException(404, "Discussion not found")
    return post


def reply_topic(db, reply):
    """The topic a topic comment or nested reply belongs to, if any."""
    if reply.target_kind == "competition-comment":
        parent = db.get(ContentReply, reply.target_id)
        return reply_topic(db, parent) if parent else None
    if reply.target_kind == "competition-post":
        return db.get(CompetitionPost, reply.target_id)
    return None


def target_row(db, kind, id, user):
    """The item of a content kind if the user may currently see it, else None."""
    if id is None:
        return None
    if kind == "code":
        return db.scalar(
            select(Notebook).where(Notebook.id == id, visible_notebooks(user))
        )
    if kind == "dataset":
        return db.scalar(
            select(Dataset).where(Dataset.id == id, visible_datasets(user))
        )
    if kind == "model":
        row = db.get(ModelCard, id)
        return row if row and can_view(row, user) else None
    if kind == "competition-post":
        row = db.get(CompetitionPost, id)
        return row if topic_visible(db, row, user) else None
    if kind == "notebook-comment":
        row = db.get(NotebookComment, id)
        if not row or not can_view(row, user):
            return None
        return row if target_row(db, "code", row.notebook_id, user) else None
    if kind in ("reply", "competition-comment"):
        row = db.get(ContentReply, id)
        if not row or not can_view(row, user):
            return None
        parent_kind = {"competition-comment": "reply"}.get(
            row.target_kind, row.target_kind
        )
        if parent_kind not in ("competition-post", "notebook-comment", "reply"):
            return None
        return row if target_row(db, parent_kind, row.target_id, user) else None
    if kind == "competition":
        return db.get(Competition, id)
    if kind == "profile":
        target = db.get(User, id)
        if not target:
            return None
        from .accounts import visible_profile

        try:
            return visible_profile(db, target.username, user)
        except HTTPException:
            return None
    return None


def target_url(db, kind, row):
    """In-app link for an item (a row of the kind's model)."""
    if row is None:
        return None
    if kind == "code":
        return f"#code/{row.id}"
    if kind == "dataset":
        return f"#datasets/{row.id}"
    if kind == "model":
        return f"#models/{row.id}"
    if kind == "competition":
        return f"#competitions/{row.id}/leaderboard"
    if kind == "profile":
        return f"#profile/{row.username}"
    if kind == "competition-post":
        if row.scope == "competition" and row.competition_id is not None:
            return f"#competitions/{row.competition_id}/discussion/{row.id}"
        return f"#discussions/{row.id}"
    if kind == "notebook-comment":
        return f"#code/{row.notebook_id}"
    if kind in ("reply", "competition-comment"):
        if row.target_kind == "notebook-comment":
            parent = db.get(NotebookComment, row.target_id)
            return f"#code/{parent.notebook_id}" if parent else None
        topic = reply_topic(db, row)
        return target_url(db, "competition-post", topic) if topic else None
    return None


def target_title(db, kind, row):
    """A short, human title for an item the viewer is allowed to see."""
    if row is None:
        return None
    if kind in ("code", "dataset", "model", "competition", "competition-post"):
        return row.title
    if kind == "profile":
        return row.username
    if kind == "notebook-comment":
        notebook = db.get(Notebook, row.notebook_id)
        return f"Comment on {notebook.title}" if notebook else "Comment"
    if kind in ("reply", "competition-comment"):
        if row.target_kind == "notebook-comment":
            parent = db.get(NotebookComment, row.target_id)
            notebook = db.get(Notebook, parent.notebook_id) if parent else None
            return f"Reply on {notebook.title}" if notebook else "Reply"
        topic = reply_topic(db, row)
        return f"Comment on {topic.title}" if topic else "Comment"
    return None


def topic_settings(db, post_id):
    return db.get(CompetitionTopicSettings, post_id)


def topic_locked(db, post):
    settings = topic_settings(db, post.id)
    return bool(settings and settings.locked)


def require_open_topic(db, post):
    """Refuse new comments and replies on locked, deleted or archived-forum topics."""
    if post.deleted_at:
        raise HTTPException(409, "This topic was deleted")
    if topic_locked(db, post):
        raise HTTPException(409, "This topic is locked; new comments are closed")
    if post.scope == "forum":
        forum = db.get(Forum, post.scope_id)
        if forum and forum.archived:
            raise HTTPException(409, "This forum is archived and read-only")


def can_moderate_topic(db, post_or_scope, user, scope_id=None):
    """Pin and lock: administrators, competition hosts and dataset/model owners."""
    from .models import ChallengeDetails
    from .permissions import can_manage

    if not user:
        return False
    if is_admin(user):
        return True
    if isinstance(post_or_scope, CompetitionPost):
        scope, scope_id = post_or_scope.scope, post_or_scope.scope_id
    else:
        scope = post_or_scope
    if scope == "competition":
        row = db.get(ChallengeDetails, scope_id) if scope_id is not None else None
        return bool(row and can_manage(user, row.owner_id))
    if scope in ("dataset", "model"):
        row = scope_row(db, scope, scope_id)
        return bool(row and row.owner_id == user.id)
    return False


# @username outside code. Usernames are 3-40 letters, digits or underscores.
MENTION = re.compile(r"(?<![\w@./+-])@([A-Za-z0-9_]{3,40})(?![\w@])")
CODE = re.compile(r"```.*?(?:```|$)|~~~.*?(?:~~~|$)|`[^`\n]*`", re.DOTALL)
MAX_MENTIONS = 20


def mentioned_names(text):
    names = []
    for match in MENTION.finditer(CODE.sub(" ", text or "")):
        name = match.group(1).lower()
        if name not in names:
            names.append(name)
    return names[:MAX_MENTIONS]


def mentioned_users(db, text):
    names = mentioned_names(text)
    if not names:
        return []
    return list(db.scalars(select(User).where(User.username.in_(names))))


def add_mentions(db, items, key="body"):
    """Add `mentions`: the mentioned usernames that exist, for profile links."""
    wanted = {name for item in items for name in mentioned_names(item.get(key))}
    existing = (
        set(db.scalars(select(User.username).where(User.username.in_(wanted))))
        if wanted
        else set()
    )
    for item in items:
        item["mentions"] = [
            name for name in mentioned_names(item.get(key)) if name in existing
        ]
    return items


def save_revision(db, kind, row, editor):
    """Keep the current text before an edit or author deletion (visible to admins)."""
    db.add(
        ContentRevision(
            target_kind=kind,
            target_id=row.id,
            editor_id=editor.id if editor else None,
            title=getattr(row, "title", None),
            body=row.body,
        )
    )


def mark_edited(row):
    row.edited_at = now()
