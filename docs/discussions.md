# Competition discussions

A discussion is a competition topic with a title and Markdown body. Each topic
has its own comments. Existing competition-post replies remain the comments of
their original topic; no copying or reassignment is required.

The competition Discussion tab and global Discussions page use the same list.
Both support search, All/Owned/Bookmarks filters, a without-comments filter,
and sorting by recent comments, newest topics, votes, or comment count. Pinned
topics appear first. Lists load 30 topics at a time. Only the competition
organizer can pin or unpin topics; bookmarks belong to individual users.

New discussion opens a right sidebar on a competition's list. Topic links open
`#competitions/<competition-id>/discussion/<topic-id>`. The detail page contains
the topic and its comments, without a new-topic button. Older global discussion
links redirect to this route.

Both editors support Markdown formatting, headings, lists, quotes, code blocks,
tables, links, image uploads, and a sanitized preview. Topic bodies allow 20,000
characters and comments allow 10,000 characters. PNG, JPEG, GIF, and WebP uploads
are limited to 5 MB; file signatures determine the served content type. Images
are public, like competition discussions.

Topic bodies, comments, pins, bookmarks, and image metadata persist in the
database. Uploaded image bytes persist under `DATA_DIR/discussion-images/`, using
opaque filenames. Competition deletion queues those files for cleanup. An image
uploaded into an abandoned editor currently remains until its competition is
deleted.

Comments also support one level of replies. Each reply is stored separately as a
`ContentReply` with target kind `competition-comment` and its parent comment ID.
Replies use the same formatting and image editor and display the author's photo.
Comments support like/helpful/celebrate reactions. Users can delete their own
replies; deleting a parent comment removes its replies and reactions. Replies
load in pages of 50 beneath their parent, without mixing into the topic's main
comment list.
