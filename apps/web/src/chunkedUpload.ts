import { api, type VersionFile } from './api';

/** A resumable upload session; see apps/api/app/uploads.py. */
export type UploadSession = {
  id: string;
  version_id: number;
  path: string;
  size: number;
  sha256: string;
  chunk_size: number;
  chunk_count: number;
  received: number[];
  received_bytes: number;
  status: 'uploading' | 'assembling' | 'completed' | 'failed';
  error: string;
  expires_at: number;
  file: VersionFile | null;
};

// Whole-file digests need the file in memory; larger files rely on per-chunk digests.
const HASH_LIMIT = 256 * 1024 * 1024;
const ATTEMPTS = 5;

export class UploadError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
  ) {
    super(message);
  }
}

/** Session ids survive page reloads, keyed by the draft, the path and the file identity. */
function storageKey(file: File, versionId: number, path: string) {
  return `arena-upload:${versionId}:${path}:${file.name}:${file.size}:${file.lastModified}`;
}
function remember(key: string, id: string) {
  try {
    localStorage.setItem(key, id);
  } catch {
    // Storage can be unavailable (private windows); uploads still resume within the page.
  }
}
function recall(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function forget(key: string) {
  try {
    localStorage.removeItem(key);
  } catch {
    // Nothing to clean up.
  }
}

async function sha256(blob: Blob) {
  // SubtleCrypto exists only on HTTPS and localhost; the server hashes regardless.
  if (!globalThis.crypto?.subtle) return '';
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function paused() {
  return new DOMException('Upload paused', 'AbortError');
}

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) return reject(paused());
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(paused());
      },
      { once: true },
    );
  });
}

async function detail(response: Response) {
  const data = await response.json().catch(() => ({}));
  return typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`;
}

/**
 * Upload a file into a draft version in chunks. Resumes a remembered session, retries
 * failed chunks with backoff, and rejects with an AbortError when the signal pauses it.
 */
export async function uploadFile(
  file: File,
  versionId: number,
  path: string,
  options: {
    signal: AbortSignal;
    onProgress: (sent: number) => void;
    onAssembling?: () => void;
  },
): Promise<UploadSession> {
  const { signal, onProgress } = options;
  const key = storageKey(file, versionId, path);
  let session: UploadSession | null = null;
  const saved = recall(key);
  if (saved) {
    session = await api<UploadSession>(`/uploads/${saved}`).catch(() => null);
    if (!session || session.status === 'failed' || session.size !== file.size) {
      forget(key);
      session = null;
    }
  }
  if (!session) {
    const digest = file.size <= HASH_LIMIT ? await sha256(file) : '';
    session = await api<UploadSession>('/uploads', {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId, path, size: file.size, sha256: digest }),
    });
    remember(key, session.id);
  }
  const current = session;
  const end = (index: number) => Math.min(file.size, (index + 1) * current.chunk_size);
  const received = new Set(current.received);
  let sent = current.received.reduce(
    (total, index) => total + end(index) - index * current.chunk_size,
    0,
  );
  onProgress(sent);
  if (current.status === 'uploading') {
    for (let index = 0; index < current.chunk_count; index += 1) {
      if (received.has(index)) continue;
      const blob = file.slice(index * current.chunk_size, end(index));
      for (let attempt = 1; ; attempt += 1) {
        if (signal.aborted) throw paused();
        try {
          const digest = await sha256(blob);
          const response = await fetch(`/api/uploads/${current.id}/chunks/${index}`, {
            method: 'PUT',
            body: blob,
            signal,
            credentials: 'same-origin',
            headers: {
              'X-Arena-Client': 'web',
              'Content-Type': 'application/octet-stream',
              ...(digest ? { 'X-Chunk-Sha256': digest } : {}),
            },
          });
          if (response.ok) break;
          const message = await detail(response);
          if (response.status === 404) forget(key);
          // Server errors, rate limits and corrupted chunks are retried; other refusals are final.
          const retryable = response.status >= 500 || [408, 422, 429].includes(response.status);
          if (!retryable || attempt >= ATTEMPTS) throw new UploadError(message, retryable);
        } catch (error) {
          if (signal.aborted || (error as Error).name === 'AbortError') throw paused();
          if (error instanceof UploadError) throw error;
          if (attempt >= ATTEMPTS)
            throw new UploadError('The connection was interrupted. Retry to continue.', true);
        }
        await sleep(Math.min(30000, 1000 * 2 ** attempt), signal);
      }
      sent += blob.size;
      onProgress(sent);
    }
    session = await api<UploadSession>(`/uploads/${current.id}/complete`, { method: 'POST' });
  }
  options.onAssembling?.();
  while (session.status === 'assembling') {
    await sleep(1500, signal);
    session = await api<UploadSession>(`/uploads/${current.id}`);
  }
  forget(key);
  if (session.status !== 'completed')
    throw new UploadError(session.error || 'The upload failed. Upload the file again.', false);
  return session;
}

/** Cancel a remembered upload and delete its parts on the server. */
export async function cancelUpload(file: File, versionId: number, path: string) {
  const key = storageKey(file, versionId, path);
  const id = recall(key);
  forget(key);
  if (id) await api(`/uploads/${id}`, { method: 'DELETE' }).catch(() => {});
}
