export type User = {
  id: number;
  username: string;
  role?: 'user' | 'host' | 'admin';
  status?: 'active' | 'suspended';
  can_create_competitions?: boolean;
  /** False for accounts created by Keycloak sign-in. */
  has_password?: boolean;
};
export type Site = {
  registration_open: boolean;
  local_login_enabled: boolean;
  announcement: string;
  oidc_enabled: boolean;
  oidc_label: string;
};
/** Full-page navigation target that starts Keycloak sign-in or account linking. */
export function oidcLoginPath(next: string, link = false) {
  const parameters = new URLSearchParams({ next: next.replace(/^#/, '') || 'home' });
  if (link) parameters.set('link', '1');
  return `/api/auth/oidc/login?${parameters}`;
}
const SSO_ERRORS: Record<string, string> = {
  state: 'That sign-in attempt is no longer valid. Please try again.',
  expired: 'Sign-in took too long and expired. Please try again.',
  denied: 'Sign-in was cancelled.',
  suspended: 'This account is suspended. Contact an administrator for help.',
  busy: 'Sign-in is busy right now. Please try again in a few minutes.',
  signin: 'Sign in to Arena before linking a Keycloak account.',
  linked: 'That Keycloak account is already linked to a different Arena account.',
  link_exists: 'Your account is already linked to another Keycloak account. Unlink it first.',
};
export function ssoErrorMessage(code: string) {
  return (
    SSO_ERRORS[code] ||
    'Single sign-on did not complete. Please try again, or contact an administrator if this continues.'
  );
}
export type Item = {
  id: number;
  title: string;
  description?: string;
  owner?: string;
  owner_id?: number;
  tags?: string;
  size?: number;
  license?: string;
  filename?: string;
  category?: string;
  metric?: string;
  evaluation_available?: boolean;
  source_url?: string;
  rules_url?: string;
  rules_content?: string;
  submission_columns?: string[];
  prize?: string;
  deadline?: string | null;
  hidden?: boolean | number;
  hidden_reason?: string;
  code?: string;
  duration?: string;
  lessons?: { title: string; body: string; code: string }[];
  body?: string;
  framework?: string;
  url?: string;
  preview?: Record<string, string>[];
  participants?: number;
  leaderboard?: { rank: number; username: string; score: number }[];
};
async function request(path: string, init: RequestInit = {}) {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: {
      'X-Arena-Client': 'web',
      ...(init.body && !(init.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join('; ')
          : `Request failed (${response.status})`,
    );
  }
  return response;
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await request(path, init);
  return response.status === 204 ? (undefined as T) : response.json();
}
/** A list page; the total comes from the X-Total-Count header. */
export async function apiPage<T>(path: string): Promise<{ items: T[]; total: number }> {
  const response = await request(path);
  const items = (await response.json()) as T[];
  const total = Number(response.headers.get('X-Total-Count'));
  return { items, total: Number.isFinite(total) && total >= items.length ? total : items.length };
}
