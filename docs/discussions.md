# Discussions

A discussion is a topic with a title and Markdown body. Topics belong to a
competition, a site forum, a dataset or a model; see [community](community.md)
for forums, scopes, votes, mentions, notifications and progression. Each topic
has its own comments. Existing competition-post replies remain the comments of
their original topic; no copying or reassignment is required.

The competition Discussion tab, forum pages, dataset and model Discussion
sections and the global Discussions page use the same list. They support search,
All/Owned/Bookmarks/Watching filters, a without-comments filter, and sorting by
recent comments, hot topics, newest topics, votes, or comment count. Pinned topics
appear first; locked topics show a lock. Lists load 30 topics at a time (10 on
dataset and model pages). Competition organizers, dataset and model owners and
administrators can pin, unpin, lock and unlock topics in their scope;
administrators manage forum topics. Bookmarks and watches belong to individual
users.

New discussion opens a right sidebar on a scoped list. Competition topic links
open `#competitions/<competition-id>/discussion/<topic-id>`; forum, dataset and
model topics open `#discussions/<topic-id>`, and `#discussions/<id>` redirects
competition topics to their competition. `#discussions/forums/<forum-id>` lists a
forum's topics. The detail page contains the topic and its comments, without a
new-topic button.

Both editors support Markdown formatting, headings, lists, quotes, code blocks,
tables, links, @mentions, and a sanitized preview. Competition discussions also
support image uploads. Topic bodies allow 20,000 characters and comments allow
10,000 characters. PNG, JPEG, GIF, and WebP uploads are limited to 5 MB; file
signatures determine the served content type. Images are public, like competition
discussions.

Topic bodies, comments, pins, locks, bookmarks, watches, revisions and image
metadata persist in the database. Uploaded image bytes persist under
`DATA_DIR/discussion-images/`, using opaque filenames. Competition deletion queues
those files for cleanup. An image uploaded into an abandoned editor currently
remains until its competition is deleted. Deleting a dataset or model deletes its
topics.

Comments also support one level of replies. Each reply is stored separately as a
`ContentReply` with target kind `competition-comment` and its parent comment ID.
Replies use the same formatting editor and display the author's photo and tier.
Topics, comments and replies can be upvoted and support like/helpful/celebrate
reactions. Authors can edit their topics, comments and replies ("edited" shows the
time; administrators can view earlier revisions) and delete them: a topic or
comment that has replies remains as a "deleted by its author" placeholder, anything
else is removed. Locked topics refuse new comments and replies. Replies load in
pages of 50 beneath their parent, without mixing into the topic's main comment
list.
