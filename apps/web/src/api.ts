export type User = {
  id: number;
  username: string;
  role?: 'user' | 'host' | 'admin';
  status?: 'active' | 'suspended';
  can_create_competitions?: boolean;
};
export type Site = {
  registration_open: boolean;
  local_login_enabled: boolean;
  announcement: string;
};
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
