import { Menu, Database, List, ChevronDown } from 'lucide-react';
import { useId } from 'react';
import { nav, dataHubPages, morePages, type Page } from './navigation';
import ActiveEvents from './ActiveEvents';
import CreateDropdown from './CreateDropdown';

type Props = {
  page: Page;
  compact: boolean;
  toggle: () => void;
  dataHubOpen: boolean;
  setDataHubOpen: (open: boolean) => void;
  moreOpen: boolean;
  setMoreOpen: (open: boolean) => void;
  signedIn: boolean;
  hasWork: boolean;
  disabled?: boolean;
  className?: string;
  navigate: (page: Page) => void;
  create: (page: Page) => void;
};
export default function Sidebar({
  page,
  compact,
  toggle,
  dataHubOpen,
  setDataHubOpen,
  moreOpen,
  setMoreOpen,
  signedIn,
  hasWork,
  disabled = false,
  className = '',
  navigate,
  create,
}: Props) {
  const groupId = useId();
  function navigationItem(item: (typeof nav)[number]) {
    return (
      <button
        disabled={disabled}
        key={item.id}
        className={page === item.id ? 'active' : ''}
        aria-label={item.label}
        title={item.label}
        aria-current={page === item.id ? 'page' : undefined}
        onClick={() => {
          navigate(item.id);
        }}
      >
        <item.icon size={19} />
        <span className="navigation-label">{item.label}</span>
      </button>
    );
  }

  return (
    <aside className={`sidebar ${compact ? 'is-compact' : ''} ${className}`}>
      <div className="sidebar-header">
        <button
          className="navigation-toggle"
          aria-label={compact ? 'Expand navigation' : 'Collapse navigation'}
          title={compact ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!compact}
          onClick={() => {
            toggle();
            setDataHubOpen(compact);
            setMoreOpen(compact);
          }}
        >
          <Menu size={21} />
        </button>
        <button
          className="brand"
          disabled={disabled}
          aria-label="Arena home"
          hidden={compact}
          onClick={() => navigate('home')}
        >
          <span className="brand-symbol">
            a<span />
          </span>
          <span className="navigation-label">
            arena<span className="brand-dot">.</span>
          </span>
        </button>
      </div>
      <CreateDropdown disabled={disabled} onSelect={(target) => create(target as Page)} />
      <nav aria-label="Main navigation">
        {nav
          .filter((item) => ['home', 'competitions', 'benchmarks'].includes(item.id))
          .map(navigationItem)}
        <div className="data-hub-group">
          <button
            className={`data-hub-toggle ${dataHubPages.includes(page) ? 'selected' : ''}`}
            aria-label="Data Hub"
            title="Data Hub"
            aria-expanded={dataHubOpen}
            aria-controls={`${groupId}-data`}
            onClick={() => setDataHubOpen(!dataHubOpen)}
          >
            <Database size={19} />
            <span className="navigation-label">Data Hub</span>
            <ChevronDown
              size={16}
              className={`navigation-chevron ${dataHubOpen ? 'expanded' : ''}`}
            />
          </button>
          <div
            id={`${groupId}-data`}
            className="data-hub-items"
            role="group"
            aria-label="Data Hub"
            hidden={!dataHubOpen}
          >
            {nav.filter((item) => dataHubPages.includes(item.id)).map(navigationItem)}
          </div>
        </div>
        <div className="more-navigation">
          <button
            type="button"
            className="more-navigation-toggle"
            aria-label="More"
            title="More"
            aria-expanded={moreOpen}
            aria-controls={`${groupId}-more`}
            onClick={() => setMoreOpen(!moreOpen)}
          >
            <List size={20} />
            <span className="navigation-label">More</span>
            <ChevronDown size={16} className={`navigation-chevron ${moreOpen ? 'expanded' : ''}`} />
          </button>
          <div
            id={`${groupId}-more`}
            className="more-navigation-items"
            role="group"
            aria-label="More"
            hidden={!moreOpen}
          >
            {nav.filter((item) => morePages.includes(item.id)).map(navigationItem)}
          </div>
        </div>
        {signedIn && hasWork && (
          <div className="your-work-navigation">
            {navigationItem(nav.find((item) => item.id === 'work')!)}
          </div>
        )}
      </nav>
      <ActiveEvents compact={compact} signedIn={signedIn} create={create} />
    </aside>
  );
}
