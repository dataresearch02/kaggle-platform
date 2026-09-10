import ActiveEvents from './ActiveEvents';
import { Menu, Ellipsis, Database } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from './api';
import { nav, dataHubPages, morePages, type Page } from './navigation';

/** The platform sidebar in its compact form, shared by notebook editors. */
export default function PlatformRail({
  expanded,
  toggle,
  signedIn,
  permanent,
  disabled,
  navigate,
}: {
  expanded: boolean;
  toggle: () => void;
  signedIn: boolean;
  permanent: boolean;
  disabled: boolean;
  navigate: (page: Page) => void;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  useEffect(() => {
    setDataOpen(expanded);
    setMoreOpen(expanded);
  }, [expanded]);
  const [hasWork, setHasWork] = useState(false);
  useEffect(() => {
    let active = true;
    setHasWork(false);
    if (signedIn)
      void api<{ has_work: boolean }>('/work/status')
        .then((result) => {
          if (active) setHasWork(result.has_work);
        })
        .catch(() => {});
    return () => {
      active = false;
    };
  }, [signedIn, permanent]);

  const item = (entry: (typeof nav)[number]) => (
    <button
      key={entry.id}
      type="button"
      aria-label={entry.label}
      title={entry.label}
      aria-current={entry.id === 'notebooks' ? 'page' : undefined}
      disabled={disabled}
      onClick={() => navigate(entry.id)}
    >
      <entry.icon size={21} />
      {expanded && <span>{entry.label}</span>}
    </button>
  );

  return (
    <nav
      className={`notebook-rail platform-rail ${expanded ? 'expanded' : ''}`}
      aria-label="Platform navigation"
    >
      <div className="sidebar-header">
        <button
          type="button"
          aria-label={expanded ? 'Collapse navigation' : 'Expand navigation'}
          title={expanded ? 'Collapse navigation' : 'Expand navigation'}
          aria-expanded={expanded}
          onClick={toggle}
        >
          <Menu size={21} />
        </button>
        <button
          type="button"
          hidden={!expanded}
          aria-label="Arena home"
          title="Arena home"
          disabled={disabled}
          onClick={() => navigate('home')}
        >
          <span className="brand-symbol" aria-hidden="true">
            a<span />
          </span>
          {expanded && <strong>arena.</strong>}
        </button>
      </div>
      {nav.filter((entry) => ['home', 'competitions', 'benchmarks'].includes(entry.id)).map(item)}
      <button
        aria-label="Data Hub"
        title="Data Hub"
        aria-expanded={dataOpen}
        onClick={() => setDataOpen(!dataOpen)}
      >
        <Database size={21} />
        {expanded && <span>Data Hub</span>}
      </button>
      <div className="platform-rail-group" role="group" aria-label="Data Hub" hidden={!dataOpen}>
        {nav.filter((entry) => dataHubPages.includes(entry.id)).map(item)}
      </div>
      <button
        type="button"
        aria-label="More"
        title="More"
        aria-expanded={moreOpen}
        onClick={() => setMoreOpen(!moreOpen)}
      >
        <Ellipsis size={21} />
        {expanded && <span>More</span>}
      </button>
      <div className="more-navigation-items" role="group" aria-label="More" hidden={!moreOpen}>
        {nav.filter((entry) => morePages.includes(entry.id)).map(item)}
      </div>
      {signedIn && (hasWork || permanent) && (
        <div className="your-work-navigation">
          {item(nav.find((entry) => entry.id === 'work')!)}
        </div>
      )}
      <ActiveEvents compact={!expanded} signedIn={signedIn} />
    </nav>
  );
}
