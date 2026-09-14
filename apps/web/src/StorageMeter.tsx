import { useEffect, useState } from 'react';
import { HardDrive } from 'lucide-react';
import { api, formatBytes, type StorageUsage } from './api';

/** The signed-in user's dataset and model storage against their quota. */
export default function StorageMeter({
  revision = 0,
  compact = false,
}: {
  revision?: number;
  compact?: boolean;
}) {
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api<StorageUsage>('/storage/usage')
      .then((row) => {
        if (active) setUsage(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [revision]);
  if (!usage) return compact ? null : <p className="muted">{error || 'Loading storage…'}</p>;
  const percent =
    usage.quota_bytes > 0 ? Math.min(100, (usage.used_bytes / usage.quota_bytes) * 100) : 100;
  return (
    <section
      className={`gpu-meter storage-meter${compact ? ' compact' : ''}`}
      aria-label="Storage used"
    >
      <div className="gpu-meter-heading">
        <HardDrive size={16} aria-hidden="true" />
        <strong>Storage</strong>
        <span>
          {formatBytes(usage.used_bytes)} of {formatBytes(usage.quota_bytes)} used
        </span>
      </div>
      <div
        className="gpu-meter-track"
        role="meter"
        aria-label="Storage used"
        aria-valuemin={0}
        aria-valuemax={usage.quota_bytes}
        aria-valuenow={usage.used_bytes}
      >
        <div className={percent >= 90 ? 'high' : undefined} style={{ width: `${percent}%` }} />
      </div>
      <p>
        {formatBytes(usage.available_bytes)} available for new uploads
        {usage.reserved_bytes
          ? ` · ${formatBytes(usage.reserved_bytes)} held by unfinished uploads`
          : ''}
        {usage.custom_quota ? ' · quota set by an administrator' : ''}
      </p>
      {!compact && (
        <p className="muted">
          Dataset and model files you own count once, even when several versions share them.
          Delete versions, datasets or models you no longer need to free space.
        </p>
      )}
    </section>
  );
}
