import ProfilePhoto from './ProfilePhoto';
import { Pin } from 'lucide-react';

export default function DiscussionAvatar({
  username,
  pinned = false,
}: {
  username: string;
  pinned?: boolean;
}) {
  const source = `/api/profiles/${encodeURIComponent(username)}/avatar`;
  return (
    <span className="discussion-avatar">
      <ProfilePhoto src={source} alt={`${username}'s profile photo`} />
      {pinned && <Pin size={13} aria-hidden="true" />}
    </span>
  );
}
