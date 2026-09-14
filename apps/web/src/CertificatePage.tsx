import { useEffect, useState } from 'react';
import { Award, Printer } from 'lucide-react';
import { api, type Certificate } from './api';

export function certificateRouteFromHash() {
  const match = window.location.hash.match(/^#certificates\/([A-Za-z0-9-]{5,40})$/);
  return match ? match[1] : null;
}

/** `#certificates/{code}`: a printable certificate verified against the public API. */
export default function CertificatePage({ code }: { code: string }) {
  const [certificate, setCertificate] = useState<Certificate | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setCertificate(null);
    setError('');
    api<Certificate>(`/certificates/${encodeURIComponent(code)}`)
      .then((row) => {
        if (active) setCertificate(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [code]);
  if (error)
    return (
      <section className="certificate-page">
        <h1>Certificate not found</h1>
        <p className="error" role="alert">
          {error}
        </p>
        <p>Check the verification code and try again.</p>
      </section>
    );
  if (!certificate) return <p role="status">Verifying certificate…</p>;
  const issued = new Date(certificate.issued_at).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  return (
    <section className="certificate-page">
      <div className="certificate-toolbar">
        <span className="certificate-verified">
          <Award size={16} aria-hidden="true" /> Verified by Arena
        </span>
        <button className="button secondary" onClick={() => window.print()}>
          <Printer size={16} /> Print
        </button>
      </div>
      <article className="certificate" aria-label="Certificate of completion">
        <span className="certificate-mark" aria-hidden="true">
          <Award size={40} />
        </span>
        <p className="certificate-eyebrow">Certificate of completion</p>
        <p>This certifies that</p>
        <h1>{certificate.holder_name || certificate.holder}</h1>
        {certificate.holder_name && <p className="muted">@{certificate.holder}</p>}
        <p>passed every graded exercise in</p>
        <h2>{certificate.course_title}</h2>
        <p>on {issued}</p>
        <footer>
          <span>arena.</span>
          <span>
            Verification code <code>{certificate.code}</code>
          </span>
          <span>{`${window.location.origin}/#certificates/${certificate.code}`}</span>
        </footer>
      </article>
      {certificate.course_available && (
        <a className="text-button" href={`#courses/${certificate.course_id}`}>
          View the course
        </a>
      )}
    </section>
  );
}
