import { useState } from 'react';

export default function ProfilePhoto({ src, alt }: { src?: string | null; alt: string }) {
  const [failed, setFailed] = useState('');
  const source = src || '/api/avatar-default';
  return (
    <img
      src={failed === source ? '/api/avatar-default' : source}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(source)}
    />
  );
}
