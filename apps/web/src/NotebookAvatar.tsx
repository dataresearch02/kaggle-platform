import ProfilePhoto from './ProfilePhoto';

export type NotebookPublisher = {
  kind: 'user' | 'team';
  name: string;
  members: string[];
};

export default function NotebookAvatar({
  owner,
  publisher,
}: {
  owner: string;
  publisher?: NotebookPublisher;
}) {
  const members =
    publisher?.kind === 'team' && publisher.members.length
      ? publisher.members.slice(0, 4)
      : [owner];
  const label =
    publisher?.kind === 'team' ? `${publisher.name}: ${publisher.members.join(', ')}` : owner;
  return (
    <div
      className={`notebook-author-avatar members-${members.length}`}
      title={label}
      role="img"
      aria-label={`${label} profile photo`}
    >
      {members.map((username) => (
        <ProfilePhoto
          key={username}
          src={`/api/profiles/${encodeURIComponent(username)}/avatar`}
          alt=""
        />
      ))}
    </div>
  );
}
