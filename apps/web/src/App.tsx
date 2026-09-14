import ResourcePage from './ResourcePage';
import BenchmarkHub from './BenchmarkHub';
import DiscussionsPage from './DiscussionsPage';
import AccountMenu from './AccountMenu';
import AccountPage, { accountRouteFromHash } from './AccountPage';
import Sidebar from './Sidebar';
import Engagement from './Engagement';
import { nav, dataHubPages, morePages, type Page } from './navigation';
import CodePage from './CodePage';
import CodeList from './CodeList';
import DatasetMetadata from './DatasetMetadata';
import ArtifactFiles from './ArtifactFiles';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Code2,
  Database,
  Download,
  FlaskConical,
  GraduationCap,
  KeyRound,
  Layers3,
  Menu,
  Plus,
  Search,
  Sparkles,
  Trophy,
  X,
} from 'lucide-react';
import {
  api,
  apiPage,
  oidcLoginPath,
  ssoErrorMessage,
  type Item,
  type Site,
  type User,
} from './api';
import AdminPage, { adminRouteFromHash } from './AdminPage';
import Markdown from './Markdown';
import NotebookWorkspace from './NotebookWorkspace';
import CreatePage from './CreatePage';
import NewNotebook from './NewNotebook';
import CompetitionPage, { competitionTabs, type CompetitionTab } from './CompetitionPage';
import { RulesSummary } from './CompetitionRules';
import YourWork, { type WorkItem, type WorkKind } from './YourWork';

const PAGE_SIZE = 24;
const ANNOUNCEMENT_KEY = 'arena-announcement-dismissed';

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
  const match = location.hash.match(/^#competitions\/(\d+)(?:\/([a-z]+))?(?:\/(\d+))?$/);
  if (!match) return null;
  return {
    id: Number(match[1]),
    discussionId: match[2] === 'discussion' && match[3] ? Number(match[3]) : undefined,
    tab: competitionTabs.includes(match[2] as CompetitionTab)
      ? (match[2] as CompetitionTab)
      : ('overview' as CompetitionTab),
  };
}

function resourceRouteFromHash() {
  const match = location.hash.match(/^#(datasets|models)\/(\d+)$/);
  return match ? { kind: match[1] as 'datasets' | 'models', id: Number(match[2]) } : null;
}
function workRouteFromHash(): WorkKind | 'all' | null {
  const match = location.hash.match(
    /^#work(?:\/(datasets|models|notebooks|competitions|benchmarks))?$/,
  );
  return match ? (match[1] as WorkKind) || 'all' : null;
}

/** `#login?sso_error=<code>` after a failed Keycloak sign-in; `#login?local=1` is break-glass. */
function loginRouteFromHash() {
  const match = location.hash.match(/^#login(?:\?(.*))?$/);
  if (!match) return null;
  const parameters = new URLSearchParams(match[1] || '');
  return { error: parameters.get('sso_error') || '', local: parameters.get('local') === '1' };
}

export default function App() {
  const [resourceRoute, setResourceRoute] = useState(resourceRouteFromHash);
  const [accountRoute, setAccountRoute] = useState(accountRouteFromHash);
  const [adminRoute, setAdminRoute] = useState(adminRouteFromHash);
  const [site, setSite] = useState<Site>({
    registration_open: true,
    local_login_enabled: true,
    announcement: '',
    oidc_enabled: false,
    oidc_label: '',
  });
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(ANNOUNCEMENT_KEY) || '';
    } catch {
      return '';
    }
  });
  const [accountRevision, setAccountRevision] = useState(0);
  const [page, setPage] = useState<Page>(() => {
    const p =
      resourceRouteFromHash()?.kind ||
      (workRouteFromHash() ? 'work' : null) ||
      (location.hash.startsWith('#benchmarks/')
        ? 'benchmarks'
        : /^#discussions\/\d+$/.test(location.hash)
          ? 'discussions'
          : location.hash.slice(1));
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
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
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
  const [ssoError, setSsoError] = useState('');
  const [breakGlass, setBreakGlass] = useState(false);
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
  const [workFilter, setWorkFilter] = useState<WorkKind | 'all'>(workRouteFromHash() || 'all');
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
    api<Site>('/site')
      .then(setSite)
      .catch(() => {});
    const openLogin = () => {
      const login = loginRouteFromHash();
      if (!login) return false;
      setSsoError(login.error);
      setBreakGlass(login.local);
      setAuth('login');
      location.replace('#home');
      return true;
    };
    openLogin();
    const handler = () => {
      if (openLogin()) return;
      setResourceRoute(resourceRouteFromHash());
      const admin = adminRouteFromHash();
      setAdminRoute(admin);
      if (admin) {
        setAccountRoute(null);
        setCodeRoute(null);
        setCompetitionRoute(null);
        setSelected(null);
        setCreating(false);
        setMobile(false);
        return;
      }
      const workRoute = workRouteFromHash();
      if (workRoute) setWorkFilter(workRoute);
      const account = accountRouteFromHash();
      setAccountRoute(account);
      if (account) {
        setCodeRoute(null);
        setCompetitionRoute(null);
        setSelected(null);
        setCreating(false);
        setMobile(false);
        return;
      }
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
      const p =
        resourceRouteFromHash()?.kind ||
        (workRouteFromHash() ? 'work' : null) ||
        (location.hash.startsWith('#benchmarks/')
          ? 'benchmarks'
          : /^#discussions\/\d+$/.test(location.hash)
            ? 'discussions'
            : location.hash.slice(1));
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
    if (
      page === 'work' ||
      page === 'notebooks' ||
      page === 'discussions' ||
      page === 'benchmarks' ||
      resourceRoute ||
      competitionRoute ||
      codeRoute
    )
      return;
    let active = true;
    setLoading(true);
    setError('');
    setItems([]);
    const timer = setTimeout(
      () => {
        Promise.all([
          apiPage<Item>(listPath(0)),
          api<Record<string, number>>('/stats'),
          page === 'home' ? api<Item[]>('/datasets') : Promise.resolve(undefined),
          page === 'competitions'
            ? api<{ categories: string[] }>('/competitions/filters')
            : Promise.resolve(undefined),
        ])
          .then(([list, counts, datasets, filters]) => {
            if (active) {
              setItems(list.items);
              setTotal(list.total);
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
    resourceRoute?.id,
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

  function listPath(offset: number) {
    const target = page === 'home' ? 'competitions' : page;
    const parameters = new URLSearchParams({
      q: query,
      offset: String(offset),
      limit: String(PAGE_SIZE),
    });
    if (page === 'competitions') {
      parameters.set('status', competitionStatus);
      parameters.set('category', competitionCategory);
      parameters.set('sort', competitionSort);
    }
    return `/${target}?${parameters}`;
  }
  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = await apiPage<Item>(listPath(items.length));
      setItems((old) => [...old, ...next.items.filter((row) => !old.some((item) => item.id === row.id))]);
      setTotal(next.total);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setLoadingMore(false);
    }
  }
  // With Keycloak on and local sign-in off, only the Keycloak button is offered;
  // administrators keep the password form through #login?local=1.
  const localAuth = site.local_login_enabled || !site.oidc_enabled || breakGlass;
  const canRegister = site.registration_open && (site.local_login_enabled || !site.oidc_enabled);
  const mayCreateCompetitions = !user || user.can_create_competitions !== false;
  function createWork(target: Page) {
    if (target === 'competitions' && !mayCreateCompetitions) {
      setNotice('Only hosts and administrators can create competitions on this site.');
      return;
    }
    go(target);
    if (user) setCreating(true);
    else {
      setPendingCreate(true);
      setAuth(canRegister ? 'register' : 'login');
    }
  }
  useEffect(() => {
    const handler = (event: Event) => createWork((event as CustomEvent<Page>).detail);
    window.addEventListener('arena-create', handler);
    return () => window.removeEventListener('arena-create', handler);
  }, [user, canRegister]);

  function openWork(kind: WorkKind) {
    go('work', `work/${kind}`);
    setWorkFilter(kind);
  }
  function go(next: Page, fragment: string = next) {
    setResourceRoute(null);
    setAccountRoute(null);
    setAdminRoute(null);
    setCodeRoute(null);
    setCompetitionRoute(null);
    setCompetitionStatus('all');
    setCompetitionCategory('');
    setCompetitionSort('newest');
    if (dataHubPages.includes(next)) setDataHubOpen(true);
    if (morePages.includes(next)) setMoreOpen(true);
    location.hash = fragment;
    setPage(next);
    setSelected(null);
    setCreating(false);
    setQuery('');
    setMobile(false);
  }
  function requireAuth(action: () => void) {
    if (user) action();
    else setAuth(canRegister ? 'register' : 'login');
  }
  function changed(message: string) {
    setRevision((v) => v + 1);
    setNotice(message);
  }
  async function open(item: Item) {
    if (page === 'datasets' || page === 'models') {
      location.hash = `${page}/${item.id}`;
      return;
    }
    if (page === 'notebooks') {
      location.hash = `code/${item.id}${user?.id === item.owner_id ? '/edit' : ''}`;
      return;
    }
    if (page === 'competitions' || page === 'home') {
      location.hash = `competitions/${item.id}/overview`;
      return;
    }
    try {
      setSelected(page === 'benchmarks' ? await api<Item>(`/${page}/${item.id}`) : item);
    } catch (e) {
      setNotice((e as Error).message);
    }
  }

  return (
    <div className={`app ${compact ? 'compact-navigation' : ''}`}>
      <Sidebar
        page={page}
        compact={compact}
        toggle={() => setCompact(!compact)}
        dataHubOpen={dataHubOpen}
        setDataHubOpen={setDataHubOpen}
        moreOpen={moreOpen}
        setMoreOpen={setMoreOpen}
        signedIn={!!user}
        hasWork={hasWork}
        canCreateCompetitions={mayCreateCompetitions}
        className={mobile ? 'visible' : ''}
        navigate={(target) => {
          if (target === 'work') setWorkFilter('all');
          go(target);
        }}
        create={createWork}
      />
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
            <span className="breadcrumb-parent">
              {dataHubPages.includes(page) ? 'Data Hub' : 'Workspace'}
            </span>
            <ChevronRight size={14} />
            <span>
              {adminRoute
                ? 'Administration'
                : accountRoute
                  ? 'Your account'
                  : nav.find((n) => n.id === page)?.label}
            </span>
          </div>
          <div className="account">
            {user ? (
              <AccountMenu
                user={user}
                revision={accountRevision}
                navigate={(path) => {
                  if (path === 'work') {
                    setWorkFilter('all');
                    go('work');
                  } else if (path === 'admin') {
                    location.hash = 'admin';
                  } else {
                    setAccountRoute(path);
                    setCodeRoute(null);
                    setCompetitionRoute(null);
                    setCreating(false);
                    setSelected(null);
                    location.hash = path;
                  }
                }}
                logout={() => {
                  setUser(null);
                  setSelected(null);
                  changed('Signed out');
                }}
              />
            ) : (
              <>
                <button className="text-button" onClick={() => setAuth('login')}>
                  Sign in
                </button>
                {canRegister && (
                  <button className="button small" onClick={() => setAuth('register')}>
                    Join the community <ArrowRight size={15} />
                  </button>
                )}
              </>
            )}
          </div>
        </header>
        {site.announcement && site.announcement !== dismissed && (
          <div className="site-announcement" role="region" aria-label="Site announcement">
            <Markdown>{site.announcement}</Markdown>
            <button
              className="icon-button"
              aria-label="Dismiss announcement"
              onClick={() => {
                setDismissed(site.announcement);
                try {
                  localStorage.setItem(ANNOUNCEMENT_KEY, site.announcement);
                } catch {
                  // Storage can be unavailable; the banner stays dismissed until reload.
                }
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}
        <main>
          {adminRoute ? (
            <AdminPage
              tab={adminRoute}
              user={user}
              siteChanged={(values) => setSite((old) => ({ ...old, ...values }))}
            />
          ) : accountRoute ? (
            <AccountPage
              key={`${accountRoute}-${user?.id}`}
              route={accountRoute}
              user={user}
              updated={() => setAccountRevision((value) => value + 1)}
              signIn={() => setAuth('login')}
            />
          ) : page === 'discussions' ? (
            <DiscussionsPage user={user} signIn={() => setAuth('login')} query={query} />
          ) : codeRoute ? (
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
              discussionId={competitionRoute.discussionId}
              setTab={(tab) => {
                location.hash = `competitions/${competitionRoute.id}/${tab}`;
              }}
              user={user}
              signIn={() => setAuth('login')}
              back={() => go('competitions')}
            />
          ) : resourceRoute ? (
            <ResourcePage
              key={`${resourceRoute.kind}-${resourceRoute.id}`}
              {...resourceRoute}
              user={user}
              signIn={() => setAuth('login')}
              yourWork={() => openWork(resourceRoute.kind)}
            />
          ) : page === 'work' ? (
            <YourWork
              key={user?.id}
              items={work}
              loading={workLoading}
              error={workError}
              signedIn={!!user}
              signIn={() => setAuth('login')}
              filter={workFilter}
              refresh={() => changed('Your work updated')}
              open={(item) => {
                if (item.work_resource === 'benchmark-collections') {
                  location.hash = `benchmarks/${item.id}`;
                  return;
                }
                if (item.work_kind === 'datasets' || item.work_kind === 'models') {
                  location.hash = `${item.work_kind}/${item.id}`;
                  return;
                }
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
          ) : page === 'benchmarks' ? (
            <BenchmarkHub
              yourWork={() => {
                openWork('benchmarks');
              }}
              user={user}
              signIn={() => setAuth('login')}
              creating={creating}
              closeCreate={() => setCreating(false)}
              openLegacy={(row) => {
                void api<Item>(`/benchmarks/${row.id}`)
                  .then(setSelected)
                  .catch((e) => setNotice(e.message));
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
                    ].includes(page) &&
                      (page !== 'competitions' || mayCreateCompetitions) && (
                      <button
                        className="button"
                        onClick={() => requireAuth(() => setCreating(true))}
                      >
                        <Plus size={17} />
                        {page === 'competitions'
                          ? 'Create competition'
                          : page === 'datasets'
                            ? 'Upload dataset'
                            : page === 'models'
                              ? 'Add model card'
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
                          openWork(page as WorkKind);
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
                      {total} {total === 1 ? 'result' : 'results'}
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
                <div className="card-grid">
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
              {page !== 'home' && !loading && !error && items.length < total && (
                <div className="load-more-row">
                  <span className="muted">
                    Showing {items.length} of {total}
                  </span>
                  <button
                    className="button secondary"
                    disabled={loadingMore}
                    onClick={() => void loadMore()}
                  >
                    {loadingMore ? 'Loading…' : 'Load more'}
                  </button>
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
                        onClick={() => {
                          location.hash = `datasets/${item.id}`;
                        }}
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
      {creating && page !== 'notebooks' && page !== 'benchmarks' && (
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
          mode={canRegister ? auth : 'login'}
          canRegister={canRegister}
          localLoginEnabled={site.local_login_enabled}
          showLocal={localAuth}
          oidcEnabled={site.oidc_enabled}
          oidcLabel={site.oidc_label || 'Sign in with Keycloak'}
          ssoError={ssoError}
          toggle={() => setAuth(auth === 'login' ? 'register' : 'login')}
          close={() => {
            setAuth(null);
            setPendingCreate(false);
            setSsoError('');
            setBreakGlass(false);
          }}
          success={(u) => {
            setSsoError('');
            setBreakGlass(false);
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
  canRegister,
  localLoginEnabled,
  showLocal,
  oidcEnabled,
  oidcLabel,
  ssoError,
  toggle,
  close,
  success,
}: {
  mode: 'login' | 'register';
  canRegister: boolean;
  localLoginEnabled: boolean;
  showLocal: boolean;
  oidcEnabled: boolean;
  oidcLabel: string;
  ssoError: string;
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
      {ssoError && (
        <p className="error" role="alert">
          {ssoErrorMessage(ssoError)}
        </p>
      )}
      {oidcEnabled && (
        <a className="button sso-button" href={oidcLoginPath(location.hash.slice(1))}>
          <KeyRound size={16} />
          {oidcLabel}
        </a>
      )}
      {oidcEnabled && !canRegister && (
        <p className="auth-notice">New to Arena? Your account is created when you first sign in.</p>
      )}
      {oidcEnabled && showLocal && (
        <p className="auth-divider">
          <span>or use your Arena password</span>
        </p>
      )}
      {showLocal && mode === 'login' && !localLoginEnabled && (
        <p className="auth-notice" role="note">
          Username and password sign-in is currently limited to administrators.
        </p>
      )}
      {showLocal && <AuthForm mode={mode} submit={submit} busy={busy} error={error} />}
      {showLocal &&
        (canRegister ? (
          <button className="text-button auth-toggle" onClick={toggle}>
            {mode === 'login' ? 'New here? Create an account' : 'Already have an account? Sign in'}
          </button>
        ) : (
          !oidcEnabled && <p className="auth-notice">Registration is currently closed.</p>
        ))}
    </Modal>
  );
}

function AuthForm({
  mode,
  submit,
  busy,
  error,
}: {
  mode: 'login' | 'register';
  submit: (e: FormEvent<HTMLFormElement>) => void;
  busy: boolean;
  error: string;
}) {
  return (
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
  const [acceptRules, setAcceptRules] = useState(false);
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
            <span>
              {item.metric_label || item.metric} ·{' '}
              {item.metric_direction === 'higher' ? 'higher' : 'lower'} is better
            </span>
            <span>{item.participants} participants</span>
            <span>
              {page === 'benchmarks'
                ? 'Ongoing benchmark'
                : item.deadline
                  ? `Closes ${item.deadline.slice(0, 10)}`
                  : 'No deadline'}
            </span>
          </div>
          <details className="detail-rules">
            <summary>Rules (revision {item.rules_revision ?? 1})</summary>
            <RulesSummary item={item} hostRules />
          </details>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={acceptRules}
              onChange={(event) => setAcceptRules(event.target.checked)}
            />
            I have read and accept the rules
          </label>
          <div className="button-row">
            <button
              className="button"
              disabled={busy || !acceptRules}
              onClick={() =>
                act(async () => {
                  await api(`/${page}/${item.id}/join`, {
                    method: 'POST',
                    body: JSON.stringify({
                      accept_rules: true,
                      rules_revision: item.rules_revision,
                    }),
                  });
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
                changed(
                  `Submission scored: ${result.score.toFixed(4)} ${item.metric_label || item.metric}`,
                );
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
                  <th>Best {item.metric_label || item.metric}</th>
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
                    <th>{item.metric_label || item.metric}</th>
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
          <ArtifactFiles kind="models" id={item.id} owner={!!user && item.owner_id === user.id} />
          {item.url && (
            <p className="external-reference">
              External reference (not available offline):{' '}
              <a href={item.url} target="_blank" rel="noreferrer noopener">
                {item.url}
              </a>
            </p>
          )}
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
