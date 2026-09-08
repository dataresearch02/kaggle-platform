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
  Home,
  Layers3,
  LogOut,
  Menu,
  MessageSquare,
  Plus,
  Search,
  Sparkles,
  Trophy,
  X,
} from 'lucide-react';
import { api, type Item, type User } from './api';
import NotebookWorkspace from './NotebookWorkspace';

type Page =
  | 'home'
  | 'competitions'
  | 'datasets'
  | 'notebooks'
  | 'models'
  | 'courses'
  | 'discussions';
const nav = [
  { id: 'home', label: 'Overview', icon: Home },
  { id: 'competitions', label: 'Competitions', icon: Trophy },
  { id: 'datasets', label: 'Datasets', icon: Database },
  { id: 'notebooks', label: 'Notebooks', icon: Code2 },
  { id: 'models', label: 'Models', icon: Layers3 },
  { id: 'courses', label: 'Learn', icon: GraduationCap },
  { id: 'discussions', label: 'Discussions', icon: MessageSquare },
] as const;
const intros: Record<Page, [string, string]> = {
  home: [
    'A little curiosity. Endless possibilities.',
    'Explore data, build models, and learn something new. Your next discovery starts here.',
  ],
  competitions: [
    'Put your ideas to the test.',
    'Learn by solving a real modeling problem. Experiment, submit, and improve.',
  ],
  datasets: [
    'Great ideas start with data.',
    'Explore community datasets or share your own. Starter datasets are small synthetic examples.',
  ],
  notebooks: [
    'From a question to an insight.',
    'Open a notebook, run Python cells, and save your experiments in your own JupyterLab workspace.',
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
const starterCode =
  'import pandas as pd\n\n# Upload a CSV using the JupyterLab file browser before running.\ndf = pd.read_csv("seed-0.csv")\nprint(df.head())\n';

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

export default function App() {
  const [page, setPage] = useState<Page>(() => {
    const p = location.hash.slice(1);
    return nav.some((n) => n.id === p) ? (p as Page) : 'home';
  });
  const [user, setUser] = useState<User | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [featured, setFeatured] = useState<Item[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [auth, setAuth] = useState<'login' | 'register' | null>(null);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Item | null>(null);
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => {});
    const handler = () => {
      const p = location.hash.slice(1);
      if (nav.some((n) => n.id === p)) {
        setPage(p as Page);
        setSelected(null);
        setQuery('');
      }
    };
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    setItems([]);
    const timer = setTimeout(
      () => {
        const target = page === 'home' ? 'competitions' : page;
        Promise.all([
          api<Item[]>(`/${target}?q=${encodeURIComponent(query)}`),
          api<Record<string, number>>('/stats'),
          ...(page === 'home' ? [api<Item[]>('/datasets')] : []),
        ])
          .then(([list, counts, datasets]) => {
            if (active) {
              setItems(list as Item[]);
              setStats(counts as Record<string, number>);
              if (datasets) setFeatured(datasets as Item[]);
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
  }, [page, query, revision]);
  useEffect(() => {
    if (notice) {
      const id = setTimeout(() => setNotice(''), 5000);
      return () => clearTimeout(id);
    }
  }, [notice]);

  function go(next: Page) {
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
    try {
      setSelected(
        page === 'datasets' || page === 'competitions' || page === 'home'
          ? await api<Item>(`/${page === 'home' ? 'competitions' : page}/${item.id}`)
          : item,
      );
    } catch (e) {
      setNotice((e as Error).message);
    }
  }

  return (
    <div className="app">
      <aside className={`sidebar ${mobile ? 'visible' : ''}`}>
        <button className="brand" onClick={() => go('home')}>
          <span className="brand-symbol">
            a<span />
          </span>
          arena<span className="brand-dot">.</span>
        </button>
        <button
          className="create-button"
          onClick={() => {
            go('notebooks');
            requireAuth(() => setCreating(true));
          }}
        >
          <Plus size={20} /> Create notebook
        </button>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {nav.map((n) => (
            <button key={n.id} className={page === n.id ? 'active' : ''} onClick={() => go(n.id)}>
              <n.icon size={19} />
              {n.label}
              {page === n.id && <span className="nav-indicator" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="tiny-icon">
            <FlaskConical size={20} />
          </span>
          <strong>Small steps. Real progress.</strong>
          <p>Learn a skill, try an idea, and see where it takes you.</p>
          <button onClick={() => go('courses')}>
            Find your first course <ArrowRight size={15} />
          </button>
        </div>
        <div className="sidebar-foot">
          <span className="status-dot" /> Community edition <span>v0.1</span>
        </div>
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
            Workspace <ChevronRight size={14} />
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
                  ['notebooks', 'Notebooks to discover', Code2],
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
                {['datasets', 'notebooks', 'models', 'discussions'].includes(page) && (
                  <button className="button" onClick={() => requireAuth(() => setCreating(true))}>
                    <Plus size={17} />
                    {page === 'datasets'
                      ? 'Upload dataset'
                      : page === 'models'
                        ? 'Add model card'
                        : page === 'discussions'
                          ? 'New discussion'
                          : 'New notebook'}
                  </button>
                )}
              </div>
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
        </main>
      </div>
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
          close={() => setAuth(null)}
          success={(u) => {
            setUser(u);
            setAuth(null);
            changed(`Welcome, ${u.username}`);
          }}
        />
      )}
      {creating && (
        <CreateModal
          page={page}
          close={() => setCreating(false)}
          success={() => {
            setCreating(false);
            changed('Published to the community');
          }}
        />
      )}
      {selected && (
        <Detail
          item={selected}
          page={page === 'home' ? 'competitions' : page}
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
        {page === 'competitions' ? (
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
            {page === 'competitions' ? (
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

function CreateModal({
  page,
  close,
  success,
}: {
  page: Page;
  close: () => void;
  success: () => void;
}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const f = new FormData(e.currentTarget);
    try {
      await api(`/${page}`, {
        method: 'POST',
        body: page === 'datasets' ? f : JSON.stringify(Object.fromEntries(f)),
      });
      success();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={
        page === 'datasets'
          ? 'Share a dataset'
          : page === 'notebooks'
            ? 'Create a notebook'
            : page === 'models'
              ? 'Publish a model card'
              : 'Start a discussion'
      }
      close={close}
    >
      <p className="muted">Published entries are visible to everyone in this workspace.</p>
      <form onSubmit={submit}>
        <label>
          Title
          <input name="title" required minLength={3} maxLength={160} />
        </label>
        <label>
          {page === 'discussions' ? 'Your question or idea' : 'Description'}
          <textarea
            name={page === 'discussions' ? 'body' : 'description'}
            required
            minLength={3}
            maxLength={5000}
            rows={3}
          />
        </label>
        {page === 'datasets' && (
          <>
            <label>
              Tags
              <input name="tags" placeholder="tabular, regression" maxLength={300} />
            </label>
            <label>
              CSV file <small>UTF-8, up to 10 MB</small>
              <input name="file" type="file" accept=".csv" required />
            </label>
          </>
        )}
        {(page === 'datasets' || page === 'models') && (
          <label>
            License
            <input name="license" defaultValue="CC0-1.0" required maxLength={80} />
          </label>
        )}
        {page === 'models' && (
          <>
            <label>
              Framework
              <input
                name="framework"
                placeholder="PyTorch, scikit-learn…"
                required
                maxLength={80}
              />
            </label>
            <label>
              Model or documentation URL
              <input name="url" type="url" placeholder="https://…" required />
            </label>
            <small>This publishes metadata and a link, not a hosted model.</small>
          </>
        )}
        {page === 'notebooks' && (
          <label>
            Python code
            <textarea
              className="code-editor"
              name="code"
              defaultValue={starterCode}
              rows={8}
              maxLength={100000}
            />
          </label>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="button" disabled={busy}>
          {busy ? 'Publishing…' : 'Publish'}
          <ArrowRight size={16} />
        </button>
      </form>
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
    if (page === 'competitions' && user)
      api<typeof submissions>(`/competitions/${item.id}/submissions`)
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
      {page === 'competitions' && (
        <>
          <div className="pill-row">
            <span>{item.metric} · lower is better</span>
            <span>{item.participants} participants</span>
            <span>Closes {item.deadline?.slice(0, 10)}</span>
          </div>
          <div className="button-row">
            <button
              className="button"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  await api(`/competitions/${item.id}/join`, { method: 'POST' });
                  setItem(await api(`/competitions/${item.id}`));
                  changed('You joined the competition');
                })
              }
            >
              Join competition
            </button>
            <a className="button secondary" href={`/api/competitions/${item.id}/sample`}>
              Sample CSV <Download size={15} />
            </a>
            <a className="button secondary" href={`/api/competitions/${item.id}/test`}>
              Test data <Download size={15} />
            </a>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              act(async () => {
                const result = await api<{ score: number }>(
                  `/competitions/${item.id}/submissions`,
                  { method: 'POST', body: f },
                );
                setItem(await api(`/competitions/${item.id}`));
                setSubmissions(await api(`/competitions/${item.id}/submissions`));
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
            signedIn={Boolean(user)}
            signIn={signIn}
          />
          <details className="notebook-template">
            <summary>Community template source</summary>
            <p className="muted">
              This is the published starting point. Changes here do not overwrite an existing
              private JupyterLab working copy.
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
          <h3>Conversation</h3>
          {comments.length === 0 && <p className="muted">Be the first to reply.</p>}
          {comments.map((c) => (
            <div className="comment" key={c.id}>
              <strong>{c.owner}</strong>
              <p>{c.body}</p>
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
