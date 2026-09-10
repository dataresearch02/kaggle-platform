import ActiveEvents from './ActiveEvents';
import Engagement from './Engagement';
import { nav, dataHubPages, morePages, type Page } from './navigation';
import CodePage from './CodePage';
import CodeList from './CodeList';
import DatasetMetadata from './DatasetMetadata';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  ChevronDown,
  Code2,
  Database,
  Download,
  FlaskConical,
  GraduationCap,
  Layers3,
  LogOut,
  Menu,
  Ellipsis,
  Plus,
  Search,
  Sparkles,
  Trophy,
  X,
} from 'lucide-react';
import { api, type Item, type User } from './api';
import NotebookWorkspace from './NotebookWorkspace';
import CreatePage from './CreatePage';
import NewNotebook from './NewNotebook';
import CreateDropdown from './CreateDropdown';
import CompetitionPage, { competitionTabs, type CompetitionTab } from './CompetitionPage';
import YourWork, { type WorkItem, type WorkKind } from './YourWork';

const intros: Record<Page, [string, string]> = {
  work: ['Your work', 'Manage the content you create.'],
  home: [
    'A little curiosity. Endless possibilities.',
    'Explore data, build models, and learn something new. Your next discovery starts here.',
  ],
  competitions: [
    'Put your ideas to the test.',
    'Learn by solving a real modeling problem. Experiment, submit, and improve.',
  ],
  benchmarks: [
    'Measure your models.',
    'Create an ongoing prediction benchmark, submit results, and compare RMSE scores.',
  ],
  datasets: [
    'Great ideas start with data.',
    'Explore community datasets or share your own. Starter datasets are small synthetic examples.',
  ],
  notebooks: [
    'From a question to an insight.',
    'Open a notebook, run Python cells, and save your experiments in the Arena notebook editor.',
  ],
  models: [
    'A starting point for your next model.',
    'Discover model cards and reference links shared by the community.',
  ],
  courses: [
    'Make room for a new skill.',
    'Short, practical lessons to help you turn curiosity into confidence.',
  ],
  discussions: [
    'Better questions. Shared discoveries.',
    'Ask for help, compare approaches, and learn together.',
  ],
};

function Modal({
  title,
  close,
  children,
  wide = false,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current!;
    el.showModal();
    return () => el.close();
  }, []);
  return (
    <dialog
      className={wide ? 'wide-dialog' : undefined}
      ref={ref}
      onCancel={close}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
      aria-label={title}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="Close dialog" onClick={close}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

function codeRouteFromHash() {
  const match = location.hash.match(/^#code\/(\d+)(\/edit)?(?:\?(.*))?$/);
  if (!match) return null;
  const competition = new URLSearchParams(match[3] || '').get('competition');
  return {
    id: Number(match[1]),
    edit: !!match[2],
    competitionId: competition && /^\d+$/.test(competition) ? Number(competition) : undefined,
  };
}

function competitionRouteFromHash() {
  const match = location.hash.match(/^#competitions\/(\d+)(?:\/([a-z]+))?$/);
  if (!match) return null;
  return {
    id: Number(match[1]),
    tab: competitionTabs.includes(match[2] as CompetitionTab)
      ? (match[2] as CompetitionTab)
      : ('overview' as CompetitionTab),
  };
}

export default function App() {
  const [page, setPage] = useState<Page>(() => {
    const p = location.hash.slice(1);
    return codeRouteFromHash()
      ? 'notebooks'
      : competitionRouteFromHash()
        ? 'competitions'
        : nav.some((n) => n.id === p)
          ? (p as Page)
          : 'home';
  });
  const [codeRoute, setCodeRoute] = useState(codeRouteFromHash);
  const [competitionRoute, setCompetitionRoute] = useState(competitionRouteFromHash);
  const [user, setUser] = useState<User | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [featured, setFeatured] = useState<Item[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [query, setQuery] = useState('');
  const [competitionStatus, setCompetitionStatus] = useState('all');
  const [competitionCategory, setCompetitionCategory] = useState('');
  const [competitionSort, setCompetitionSort] = useState('newest');
  const [competitionCategories, setCompetitionCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [auth, setAuth] = useState<'login' | 'register' | null>(null);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Item | null>(null);
  const [pendingCreate, setPendingCreate] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [moreOpen, setMoreOpen] = useState(true);
  const [dataHubOpen, setDataHubOpen] = useState(true);
  const [compact, setCompact] = useState(false);
  const [hasWork, setHasWork] = useState(false);
  const [work, setWork] = useState<WorkItem[]>([]);
  const [workLoading, setWorkLoading] = useState(false);
  const [workError, setWorkError] = useState('');
  const [workFilter, setWorkFilter] = useState<WorkKind | 'all'>('all');
  const [workSelection, setWorkSelection] = useState<WorkKind>('notebooks');
  useEffect(() => {
    let active = true;
    setWork((previous) => previous.filter((item) => item.owner_id === user?.id));
    setWorkError('');
    if (!user) {
      setHasWork(false);
      setWorkLoading(false);
      return;
    }
    if (page !== 'work') {
      api<{ has_work: boolean }>('/work/status')
        .then((result) => {
          if (active) setHasWork(result.has_work);
        })
        .catch(() => {});
      return () => {
        active = false;
      };
    }
    setWorkLoading(true);
    api<WorkItem[]>('/work')
      .then((items) => {
        if (active) {
          setWork(items);
          setHasWork(items.length > 0);
        }
      })
      .catch((e) => {
        if (active) setWorkError(e.message);
      })
      .finally(() => {
        if (active) setWorkLoading(false);
      });
    return () => {
      active = false;
    };
  }, [user?.id, revision, page, creating]);

  useEffect(() => {
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => {});
    const handler = () => {
      const code = codeRouteFromHash();
      setCodeRoute(code);
      if (code) {
        setCompetitionRoute(null);
        setPage('notebooks');
        setSelected(null);
        setCreating(false);
        setMobile(false);
        return;
      }
      const route = competitionRouteFromHash();
      setCompetitionRoute(route);
      if (route) {
        setPage('competitions');
        setSelected(null);
        setCreating(false);
        setMobile(false);
        return;
      }
      const p = location.hash.slice(1);
      if (nav.some((n) => n.id === p)) {
        setPage(p as Page);
        if (dataHubPages.includes(p as Page)) setDataHubOpen(true);
        if (morePages.includes(p as Page)) setMoreOpen(true);
        setSelected(null);
        setQuery('');
        setCompetitionStatus('all');
        setCompetitionCategory('');
        setCompetitionSort('newest');
      }
    };
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  useEffect(() => {
    if (page === 'work' || page === 'notebooks' || competitionRoute || codeRoute) return;
    let active = true;
    setLoading(true);
    setError('');
    setItems([]);
    const timer = setTimeout(
      () => {
        const target = page === 'home' ? 'competitions' : page;
        const parameters = new URLSearchParams({ q: query });
        if (page === 'competitions') {
          parameters.set('status', competitionStatus);
          parameters.set('category', competitionCategory);
          parameters.set('sort', competitionSort);
        }
        Promise.all([
          api<Item[]>(`/${target}?${parameters}`),
          api<Record<string, number>>('/stats'),
          page === 'home' ? api<Item[]>('/datasets') : Promise.resolve(undefined),
          page === 'competitions'
            ? api<{ categories: string[] }>('/competitions/filters')
            : Promise.resolve(undefined),
        ])
          .then(([list, counts, datasets, filters]) => {
            if (active) {
              setItems(list as Item[]);
              setStats(counts as Record<string, number>);
              if (datasets) setFeatured(datasets as Item[]);
              if (filters) setCompetitionCategories(filters.categories);
            }
          })
          .catch((e) => {
            if (active) setError(e.message);
          })
          .finally(() => {
            if (active) setLoading(false);
          });
      },
      query ? 200 : 0,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    page,
    query,
    revision,
    competitionRoute?.id,
    codeRoute?.id,
    competitionStatus,
    competitionCategory,
    competitionSort,
  ]);
  useEffect(() => {
    if (notice) {
      const id = setTimeout(() => setNotice(''), 5000);
      return () => clearTimeout(id);
    }
  }, [notice]);

  function go(next: Page) {
    setCodeRoute(null);
    setCompetitionRoute(null);
    setCompetitionStatus('all');
    setCompetitionCategory('');
    setCompetitionSort('newest');
    if (dataHubPages.includes(next)) setDataHubOpen(true);
    if (morePages.includes(next)) setMoreOpen(true);
    location.hash = next;
    setPage(next);
    setSelected(null);
    setCreating(false);
    setQuery('');
    setMobile(false);
  }
  function requireAuth(action: () => void) {
    if (user) action();
    else setAuth('register');
  }
  function changed(message: string) {
    setRevision((v) => v + 1);
    setNotice(message);
  }
  async function open(item: Item) {
    if (page === 'notebooks') {
      location.hash = `code/${item.id}${user?.id === item.owner_id ? '/edit' : ''}`;
      return;
    }
    if (page === 'competitions' || page === 'home') {
      location.hash = `competitions/${item.id}/overview`;
      return;
    }
    try {
      setSelected(
        page === 'datasets' || page === 'benchmarks'
          ? await api<Item>(`/${page}/${item.id}`)
          : item,
      );
    } catch (e) {
      setNotice((e as Error).message);
    }
  }

  function navigationItem(item: (typeof nav)[number]) {
    return (
      <button
        key={item.id}
        className={page === item.id ? 'active' : ''}
        aria-label={item.label}
        title={item.label}
        aria-current={page === item.id ? 'page' : undefined}
        onClick={() => {
          if (item.id === 'work') setWorkFilter('all');
          go(item.id);
        }}
      >
        <item.icon size={19} />
        <span className="navigation-label">{item.label}</span>
      </button>
    );
  }

  return (
    <div className={`app ${compact ? 'compact-navigation' : ''}`}>
      <aside className={`sidebar ${mobile ? 'visible' : ''}`}>
        <div className="sidebar-header">
          <button
            className="navigation-toggle"
            aria-label={compact ? 'Expand navigation' : 'Collapse navigation'}
            title={compact ? 'Expand navigation' : 'Collapse navigation'}
            aria-expanded={!compact}
            onClick={() => {
              setCompact(!compact);
              setDataHubOpen(compact);
              setMoreOpen(compact);
            }}
          >
            <Menu size={21} />
          </button>
          <button
            className="brand"
            aria-label="Arena home"
            hidden={compact}
            onClick={() => go('home')}
          >
            <span className="brand-symbol">
              a<span />
            </span>
            <span className="navigation-label">
              arena<span className="brand-dot">.</span>
            </span>
          </button>
        </div>
        <CreateDropdown
          onSelect={(target) => {
            go(target as Page);
            if (user) setCreating(true);
            else {
              setPendingCreate(true);
              setAuth('register');
            }
          }}
        />
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
              aria-controls="data-hub-navigation"
              onClick={() => setDataHubOpen(!dataHubOpen)}
            >
              <Database size={19} />
              <span className="navigation-label">Data Hub</span>
              <ChevronDown size={16} className={dataHubOpen ? 'expanded' : ''} />
            </button>
            <div
              id="data-hub-navigation"
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
              aria-label="More"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen(!moreOpen)}
            >
              <Ellipsis size={20} />
              <span className="navigation-label">More</span>
              <ChevronDown size={16} className="navigation-label" />
            </button>
            <div
              className="more-navigation-items"
              role="group"
              aria-label="More"
              hidden={!moreOpen}
            >
              {nav.filter((item) => morePages.includes(item.id)).map(navigationItem)}
            </div>
          </div>
          {user && hasWork && (
            <div className="your-work-navigation">
              {navigationItem(nav.find((item) => item.id === 'work')!)}
            </div>
          )}
        </nav>
        <ActiveEvents
          compact={compact}
          signedIn={!!user}
          create={(target) => {
            go(target);
            if (user) setCreating(true);
            else {
              setPendingCreate(true);
              setAuth('register');
            }
          }}
        />
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            onClick={() => setMobile(!mobile)}
            aria-label="Toggle navigation"
          >
            <Menu />
          </button>
          <div className="breadcrumb">
            {dataHubPages.includes(page) ? 'Data Hub' : 'Workspace'} <ChevronRight size={14} />
            <span>{nav.find((n) => n.id === page)?.label}</span>
          </div>
          <div className="account">
            {user ? (
              <>
                <span className="avatar">{user.username[0].toUpperCase()}</span>
                <span>{user.username}</span>
                <button
                  className="icon-button"
                  title="Sign out"
                  onClick={() =>
                    api('/auth/logout', { method: 'POST' })
                      .then(() => {
                        setUser(null);
                        setSelected(null);
                        changed('Signed out');
                      })
                      .catch((e) => setNotice(e.message))
                  }
                >
                  <LogOut size={17} />
                </button>
              </>
            ) : (
              <>
                <button className="text-button" onClick={() => setAuth('login')}>
                  Sign in
                </button>
                <button className="button small" onClick={() => setAuth('register')}>
                  Join the community <ArrowRight size={15} />
                </button>
              </>
            )}
          </div>
        </header>
        <main>
          {codeRoute ? (
            <CodePage
              key={`${codeRoute.id}-${codeRoute.edit}-${user?.id}`}
              id={codeRoute.id}
              edit={codeRoute.edit}
              competitionId={codeRoute.competitionId}
              user={user}
              signIn={() => setAuth('login')}
              changed={() => changed('Your code library was updated')}
            />
          ) : competitionRoute ? (
            <CompetitionPage
              key={competitionRoute.id}
              id={competitionRoute.id}
              tab={competitionRoute.tab}
              setTab={(tab) => {
                location.hash = `competitions/${competitionRoute.id}/${tab}`;
              }}
              user={user}
              signIn={() => setAuth('login')}
              back={() => go('competitions')}
            />
          ) : page === 'work' ? (
            <YourWork
              key={`${user?.id}-${workFilter}`}
              items={work}
              loading={workLoading}
              error={workError}
              signedIn={!!user}
              signIn={() => setAuth('login')}
              initialFilter={workFilter}
              refresh={() => changed('Your work updated')}
              open={(item) => {
                if (item.work_kind === 'notebooks') {
                  location.hash = `code/${item.id}/edit`;
                  return;
                }
                if (item.work_kind === 'competitions') {
                  location.hash = `competitions/${item.id}/overview`;
                  return;
                }
                setWorkSelection(item.work_kind);
                if (['datasets', 'competitions', 'benchmarks'].includes(item.work_kind)) {
                  void api<Item>(`/${item.work_kind}/${item.id}`)
                    .then(setSelected)
                    .catch((e) => setNotice(e.message));
                } else setSelected(item);
              }}
            />
          ) : page === 'notebooks' ? (
            <CodeList key={`${user?.id}-${revision}`} user={user} signIn={() => setAuth('login')} />
          ) : (
            <>
              {page === 'home' ? (
                <>
                  <div className="eyebrow">
                    <span /> A SPACE FOR CURIOUS MINDS
                  </div>
                  <section className="hero">
                    <div className="hero-copy">
                      <h1>
                        A little curiosity.
                        <br />
                        <span>Endless possibilities.</span>
                      </h1>
                      <p>{intros.home[1]}</p>
                      <div className="hero-actions">
                        <button className="button" onClick={() => go('competitions')}>
                          Explore competitions <ArrowRight size={17} />
                        </button>
                        <button className="button secondary" onClick={() => go('courses')}>
                          Start learning <BookOpen size={17} />
                        </button>
                      </div>
                      <div className="hero-caption">
                        <span className="mini-avatars">
                          <i>A</i>
                          <i>M</i>
                          <i>J</i>
                        </span>
                        Built for everyone with a question.
                      </div>
                    </div>
                    <div className="hero-art" aria-hidden="true">
                      <div className="orbit one" />
                      <div className="orbit two" />
                      <div className="art-grid" />
                      <div className="art-card data">
                        <Database size={27} />
                        <span>EXPLORE</span>
                        <strong>Find the signal.</strong>
                        <div className="bars">
                          <i />
                          <i />
                          <i />
                          <i />
                          <i />
                          <i />
                          <i />
                        </div>
                      </div>
                      <div className="art-card code">
                        <Code2 size={24} />
                        <span>EXPERIMENT</span>
                        <div className="code-lines">
                          <i />
                          <i />
                          <i />
                        </div>
                      </div>
                      <div className="art-spark">
                        <Sparkles size={25} />
                      </div>
                      <span className="art-dot d1" />
                      <span className="art-dot d2" />
                    </div>
                  </section>
                  <div className="stats">
                    {[
                      ['datasets', 'Datasets to explore', Database],
                      ['competitions', 'Challenge to take on', Trophy],
                      ['notebooks', 'Codes to discover', Code2],
                      ['learners', 'Community accounts', GraduationCap],
                    ].map(([key, label, Icon]) => {
                      const Component = Icon as typeof Database;
                      return (
                        <div key={key as string}>
                          <span className={`stat-icon ${key}`}>
                            <Component size={21} />
                          </span>
                          <div>
                            <strong>{stats[key as string] ?? '—'}</strong>
                            <span>{label as string}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <SectionTitle
                    title="Find your next challenge"
                    subtitle="A little competition goes a long way."
                    action="All competitions"
                    click={() => go('competitions')}
                  />
                </>
              ) : (
                <>
                  <div className="eyebrow">
                    EXPLORE / {nav.find((n) => n.id === page)?.label.toUpperCase()}
                  </div>
                  <div className="page-intro">
                    <div>
                      <h1>{intros[page][0]}</h1>
                      <p>{intros[page][1]}</p>
                    </div>
                    {[
                      'datasets',
                      'notebooks',
                      'competitions',
                      'benchmarks',
                      'models',
                      'discussions',
                    ].includes(page) && (
                      <button
                        className="button"
                        onClick={() => requireAuth(() => setCreating(true))}
                      >
                        <Plus size={17} />
                        {page === 'competitions'
                          ? 'Create competition'
                          : page === 'benchmarks'
                            ? 'Create benchmark'
                            : page === 'datasets'
                              ? 'Upload dataset'
                              : page === 'models'
                                ? 'Add model card'
                                : page === 'discussions'
                                  ? 'New discussion'
                                  : 'New notebook'}
                      </button>
                    )}
                  </div>
                  {['datasets', 'models', 'notebooks', 'competitions', 'benchmarks'].includes(
                    page,
                  ) && (
                    <div className="collection-actions">
                      <button
                        className="button secondary"
                        onClick={() => {
                          setWorkFilter(page as WorkKind);
                          go('work');
                        }}
                      >
                        Your work <ArrowRight size={14} />
                      </button>
                    </div>
                  )}
                  <div className="filters">
                    <label className="search">
                      <Search size={18} />
                      <input
                        aria-label={`Search ${page}`}
                        placeholder={`Search ${page}…`}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </label>
                    <span>
                      {items.length} {items.length === 1 ? 'result' : 'results'}
                    </span>
                  </div>
                  {page === 'competitions' && (
                    <div className="competition-filters" aria-label="Competition filters">
                      <label>
                        Status
                        <select
                          aria-label="Competition status"
                          value={competitionStatus}
                          onChange={(e) => setCompetitionStatus(e.target.value)}
                        >
                          <option value="all">All competitions</option>
                          <option value="open">Open</option>
                          <option value="closed">Closed</option>
                        </select>
                      </label>
                      <label>
                        Category
                        <select
                          aria-label="Competition category"
                          value={competitionCategory}
                          onChange={(e) => setCompetitionCategory(e.target.value)}
                        >
                          <option value="">All categories</option>
                          {competitionCategories.map((category) => (
                            <option key={category} value={category}>
                              {category}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Sort by
                        <select
                          aria-label="Sort competitions"
                          value={competitionSort}
                          onChange={(e) => setCompetitionSort(e.target.value)}
                        >
                          <option value="newest">Newest</option>
                          <option value="closing">Closing soon</option>
                          <option value="title">Title A–Z</option>
                        </select>
                      </label>
                      {(query ||
                        competitionStatus !== 'all' ||
                        competitionCategory ||
                        competitionSort !== 'newest') && (
                        <button
                          className="text-button"
                          onClick={() => {
                            setQuery('');
                            setCompetitionStatus('all');
                            setCompetitionCategory('');
                            setCompetitionSort('newest');
                          }}
                        >
                          Clear filters
                        </button>
                      )}
                    </div>
                  )}
                </>
              )}
              {error ? (
                <div className="empty" role="alert">
                  <h3>We couldn’t load the workspace</h3>
                  <p>{error}</p>
                  <button className="button secondary" onClick={() => setRevision((v) => v + 1)}>
                    Try again
                  </button>
                </div>
              ) : loading ? (
                <div className="card-grid" aria-label="Loading">
                  <div className="skeleton" />
                  <div className="skeleton" />
                  <div className="skeleton" />
                </div>
              ) : items.length === 0 ? (
                <div className="empty">
                  <Search />
                  <h3>No results yet</h3>
                  <p>Try another search or create the first entry.</p>
                </div>
              ) : (
                <div className={`card-grid ${page === 'discussions' ? 'list-grid' : ''}`}>
                  {items.map((item, index) => (
                    <Card
                      key={item.id}
                      item={item}
                      page={page === 'home' ? 'competitions' : page}
                      index={index}
                      onClick={() => open(item)}
                    />
                  ))}
                </div>
              )}
              {page === 'home' && (
                <>
                  <SectionTitle
                    title="Your next discovery is in the data"
                    subtitle="A few small datasets. Plenty of possibilities."
                    action="Explore datasets"
                    click={() => go('datasets')}
                  />
                  <div className="card-grid">
                    {featured.slice(0, 3).map((item, index) => (
                      <Card
                        key={item.id}
                        item={item}
                        page="datasets"
                        index={index}
                        onClick={() => go('datasets')}
                      />
                    ))}
                  </div>
                  <section className="learn-banner">
                    <span className="learn-icon">
                      <GraduationCap size={33} />
                    </span>
                    <div>
                      <div className="eyebrow">A LITTLE LEARNING, EVERY DAY</div>
                      <h2>Your next skill is closer than you think.</h2>
                      <p>Start with Python, explore pandas, or train your first model.</p>
                    </div>
                    <button className="button secondary" onClick={() => go('courses')}>
                      Explore courses <ArrowRight size={17} />
                    </button>
                  </section>
                </>
              )}
              <footer>
                <span>
                  arena. <span>A place to learn by doing.</span>
                </span>
                <span>Open workspace · Community edition</span>
              </footer>
            </>
          )}
        </main>
      </div>
      {creating && page === 'notebooks' && (
        <NewNotebook
          close={() => setCreating(false)}
          saved={() => changed('Notebook saved permanently')}
        />
      )}
      {creating && page !== 'notebooks' && (
        <CreatePage
          key={page}
          page={page}
          close={() => setCreating(false)}
          success={() => {
            setCreating(false);
            changed('Published to the community');
          }}
        />
      )}
      {notice && (
        <div className="toast" role="status">
          {notice}
          <button aria-label="Dismiss notification" onClick={() => setNotice('')}>
            <X size={16} />
          </button>
        </div>
      )}
      {auth && (
        <AuthModal
          mode={auth}
          toggle={() => setAuth(auth === 'login' ? 'register' : 'login')}
          close={() => {
            setAuth(null);
            setPendingCreate(false);
          }}
          success={(u) => {
            setUser(u);
            if (pendingCreate) {
              setCreating(true);
              setPendingCreate(false);
            }
            setAuth(null);
            changed(`Welcome, ${u.username}`);
          }}
        />
      )}
      {selected && (
        <Detail
          item={selected}
          page={page === 'work' ? workSelection : page === 'home' ? 'competitions' : page}
          user={user}
          close={() => setSelected(null)}
          signIn={() => {
            setSelected(null);
            setAuth('login');
          }}
          changed={changed}
        />
      )}
    </div>
  );
}

function SectionTitle({
  title,
  subtitle,
  action,
  click,
}: {
  title: string;
  subtitle: string;
  action: string;
  click: () => void;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
      <button className="text-button" onClick={click}>
        {action}
        <ArrowRight size={16} />
      </button>
    </div>
  );
}
function Card({
  item,
  page,
  index,
  onClick,
}: {
  item: Item;
  page: Page;
  index: number;
  onClick: () => void;
}) {
  const Icon = nav.find((n) => n.id === page)?.icon ?? Database;
  return (
    <button className={`content-card ${page}`} onClick={onClick}>
      <div className={`card-art color-${index % 3}`}>
        <Icon size={31} />
        {page === 'competitions' || page === 'benchmarks' ? (
          <>
            <div className="mountain m1" />
            <div className="mountain m2" />
            <span className="art-label">THE FIRST STEP IS YOURS</span>
          </>
        ) : (
          <div className="art-pattern" />
        )}
        <span className="card-category">
          {item.category ||
            item.framework ||
            (page === 'datasets'
              ? 'CSV DATASET'
              : page === 'courses'
                ? 'FREE COURSE'
                : page === 'notebooks'
                  ? 'PYTHON'
                  : 'COMMUNITY')}
        </span>
      </div>
      <div className="card-body">
        <div className="card-owner">
          {item.owner
            ? `by ${item.owner}`
            : page === 'courses'
              ? `${item.lessons?.length} lessons · ${item.duration}`
              : 'Arena · Learning challenge'}
        </div>
        <h3>{item.title}</h3>
        <p>{item.description || item.body}</p>
        <div className="card-bottom">
          <span>
            {page === 'competitions' || page === 'benchmarks' ? (
              <>
                <Trophy size={14} />
                {item.prize}
              </>
            ) : page === 'datasets' ? (
              item.tags
                ?.split(',')
                .slice(0, 2)
                .map((t) => <i key={t}>{t}</i>)
            ) : page === 'courses' ? (
              'Start learning'
            ) : page === 'notebooks' ? (
              'View notebook'
            ) : page === 'models' ? (
              item.license
            ) : (
              'Join the conversation'
            )}
          </span>
          <ArrowRight size={16} />
        </div>
      </div>
    </button>
  );
}

function AuthModal({
  mode,
  toggle,
  close,
  success,
}: {
  mode: 'login' | 'register';
  toggle: () => void;
  close: () => void;
  success: (u: User) => void;
}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const f = new FormData(e.currentTarget);
    try {
      success(
        await api<User>(`/auth/${mode}`, {
          method: 'POST',
          body: JSON.stringify(Object.fromEntries(f)),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={mode === 'login' ? 'Welcome back' : 'Start your next discovery'} close={close}>
      <p className="muted">Create, learn, and share with your community.</p>
      <form onSubmit={submit}>
        <label>
          Username
          <input
            name="username"
            required
            minLength={3}
            maxLength={40}
            pattern="[a-zA-Z0-9_]+"
            autoComplete="username"
          />
        </label>
        <label>
          Password
          <input
            type="password"
            name="password"
            required
            minLength={10}
            maxLength={128}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />
          <small>At least 10 characters.</small>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="button" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          <ArrowRight size={16} />
        </button>
      </form>
      <button className="text-button auth-toggle" onClick={toggle}>
        {mode === 'login' ? 'New here? Create an account' : 'Already have an account? Sign in'}
      </button>
    </Modal>
  );
}

function Detail({
  item: initial,
  page,
  user,
  close,
  signIn,
  changed,
}: {
  item: Item;
  page: Page;
  user: User | null;
  close: () => void;
  signIn: () => void;
  changed: (m: string) => void;
}) {
  const [item, setItem] = useState(initial);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState(item.code || '');
  const [lesson, setLesson] = useState(0);
  const [progress, setProgress] = useState<number[]>([]);
  const [comments, setComments] = useState<{ id: number; owner: string; body: string }[]>([]);
  const [submissions, setSubmissions] = useState<{ id: number; filename: string; score: number }[]>(
    [],
  );
  useEffect(() => {
    let active = true;
    if (page === 'courses' && user)
      api<number[]>(`/courses/${item.id}/progress`)
        .then((data) => {
          if (active) setProgress(data);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    if (page === 'discussions')
      api<typeof comments>(`/discussions/${item.id}/comments`)
        .then((data) => {
          if (active) setComments(data);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    if ((page === 'competitions' || page === 'benchmarks') && user)
      api<typeof submissions>(`/${page}/${item.id}/submissions`)
        .then((data) => {
          if (active) setSubmissions(data);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [item.id, page, user]);
  async function act(action: () => Promise<void>) {
    if (!user) {
      signIn();
      return;
    }
    setError('');
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const currentLesson = item.lessons?.[lesson];
  return (
    <Modal title={item.title} close={close} wide={page === 'notebooks'}>
      {page !== 'notebooks' && (
        <>
          <p className="detail-description">{item.description || item.body}</p>
          {item.owner && <p className="muted">Shared by {item.owner}</p>}
        </>
      )}
      {page === 'datasets' && (
        <>
          <div className="pill-row">
            <span>{item.license}</span>
            <span>{((item.size || 0) / 1024).toFixed(1)} KB</span>
            <span>CSV</span>
          </div>
          <DatasetMetadata id={item.id} owner={!!user && item.owner_id === user.id} />
          <h3>
            Data preview <small>First 10 rows</small>
          </h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {Object.keys(item.preview?.[0] || {}).map((k) => (
                    <th key={k}>{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {item.preview?.map((row, i) => (
                  <tr key={i}>
                    {Object.entries(row).map(([k, v]) => (
                      <td key={k}>{v}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <a className="button" href={`/api/datasets/${item.id}/download`}>
            <Download size={16} />
            Download CSV
          </a>
        </>
      )}
      {(page === 'competitions' || page === 'benchmarks') && (
        <>
          <div className="pill-row">
            <span>{item.metric} · lower is better</span>
            <span>{item.participants} participants</span>
            <span>
              {page === 'benchmarks'
                ? 'Ongoing benchmark'
                : `Closes ${item.deadline?.slice(0, 10)}`}
            </span>
          </div>
          <div className="button-row">
            <button
              className="button"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  await api(`/${page}/${item.id}/join`, { method: 'POST' });
                  setItem(await api(`/${page}/${item.id}`));
                  changed(
                    page === 'benchmarks'
                      ? 'You joined the benchmark'
                      : 'You joined the competition',
                  );
                })
              }
            >
              {page === 'benchmarks' ? 'Join benchmark' : 'Join competition'}
            </button>
            <a className="button secondary" href={`/api/${page}/${item.id}/sample`}>
              Sample CSV <Download size={15} />
            </a>
            <a className="button secondary" href={`/api/${page}/${item.id}/test`}>
              Test data <Download size={15} />
            </a>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              act(async () => {
                const result = await api<{ score: number }>(`/${page}/${item.id}/submissions`, {
                  method: 'POST',
                  body: f,
                });
                setItem(await api(`/${page}/${item.id}`));
                setSubmissions(await api(`/${page}/${item.id}/submissions`));
                changed(`Submission scored: ${result.score.toFixed(4)} RMSE`);
              });
            }}
          >
            <label>
              Submit predictions
              <input name="file" type="file" accept=".csv" required />
            </label>
            <button className="button secondary" disabled={busy}>
              Score submission <ArrowRight size={16} />
            </button>
          </form>
          <h3>Leaderboard</h3>
          {item.leaderboard?.length ? (
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Participant</th>
                  <th>Best RMSE</th>
                </tr>
              </thead>
              <tbody>
                {item.leaderboard.map((row) => (
                  <tr key={row.username}>
                    <td>#{row.rank}</td>
                    <td>{row.username}</td>
                    <td>{row.score.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No submissions yet. Set the first baseline.</p>
          )}
          {submissions.length > 0 && (
            <>
              <h3>Your submissions</h3>
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <th>RMSE</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((s) => (
                    <tr key={s.id}>
                      <td>{s.filename}</td>
                      <td>{s.score.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
      {page === 'notebooks' && (
        <>
          <NotebookWorkspace
            key={item.id}
            notebookId={item.id}
            title={item.title}
            initialCode={item.code || ''}
            signedIn={Boolean(user)}
            canPublish={!!user && item.owner_id === user.id}
            signIn={signIn}
          />
          <details className="notebook-template">
            <summary>Community template source</summary>
            <p className="muted">
              This is the published starting point. Changes here do not overwrite an existing
              private notebook working copy.
            </p>
            <label>
              Python source
              <textarea
                className="code-editor"
                rows={8}
                value={code}
                maxLength={100000}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            <div className="button-row">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const own = item.owner_id === user?.id;
                    const result = await api<Item>(own ? `/notebooks/${item.id}` : '/notebooks', {
                      method: own ? 'PUT' : 'POST',
                      body: JSON.stringify({
                        title: item.title,
                        description: item.description,
                        code,
                      }),
                    });
                    setItem(result);
                    changed(own ? 'Notebook saved' : 'Your copy is saved');
                  })
                }
              >
                {item.owner_id === user?.id ? 'Save notebook template' : 'Publish my own template'}
              </button>
              <a className="text-button" href={`/api/notebooks/${item.id}/download`}>
                Download template <Download size={15} />
              </a>
            </div>
          </details>
        </>
      )}

      {page === 'courses' && (
        <>
          <div className="progress-track">
            <div style={{ width: `${(progress.length / (item.lessons?.length || 1)) * 100}%` }} />
          </div>
          <p className="muted">
            {progress.length} of {item.lessons?.length} lessons complete
          </p>
          <div className="lesson-tabs">
            {item.lessons?.map((l, i) => (
              <button
                key={l.title}
                className={lesson === i ? 'active' : ''}
                onClick={() => setLesson(i)}
              >
                {progress.includes(i) ? <Check size={15} /> : <span>{i + 1}</span>}
                {l.title}
              </button>
            ))}
          </div>
          {currentLesson && (
            <>
              <h3>{currentLesson.title}</h3>
              <p className="detail-description">{currentLesson.body}</p>
              <pre>{currentLesson.code}</pre>
              <button
                className="button"
                disabled={busy || progress.includes(lesson)}
                onClick={() =>
                  act(async () => {
                    await api(`/courses/${item.id}/lessons/${lesson}/complete`, { method: 'POST' });
                    setProgress(await api(`/courses/${item.id}/progress`));
                    changed('Progress saved');
                  })
                }
              >
                {progress.includes(lesson) ? 'Completed' : 'Mark as complete'}
                <Check size={16} />
              </button>
            </>
          )}
        </>
      )}
      {page === 'discussions' && (
        <>
          <Engagement
            kind="discussion"
            id={item.id}
            user={user}
            signIn={signIn}
            allowReply={false}
          />
          <h3>Conversation</h3>
          {comments.length === 0 && <p className="muted">Be the first to reply.</p>}
          {comments.map((c) => (
            <div className="comment" key={c.id}>
              <strong>{c.owner}</strong>
              <p>{c.body}</p>
              <Engagement kind="discussion-comment" id={c.id} user={user} signIn={signIn} />
            </div>
          ))}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const body = new FormData(form).get('body');
              act(async () => {
                await api(`/discussions/${item.id}/comments`, {
                  method: 'POST',
                  body: JSON.stringify({ body }),
                });
                setComments(await api(`/discussions/${item.id}/comments`));
                form.reset();
                changed('Reply posted');
              });
            }}
          >
            <label>
              Your reply
              <textarea name="body" required maxLength={5000} rows={3} />
            </label>
            <button className="button" disabled={busy}>
              Post reply <ArrowRight size={16} />
            </button>
          </form>
        </>
      )}
      {page === 'models' && (
        <>
          <div className="pill-row">
            <span>{item.framework}</span>
            <span>{item.license}</span>
          </div>
          <p className="info">
            This is a model reference card. Hosted inference and model artifact storage are planned
            for a later milestone.
          </p>
          <a className="button" href={item.url} target="_blank" rel="noreferrer">
            Visit model reference ↗
          </a>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Modal>
  );
}
