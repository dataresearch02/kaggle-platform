import { useEffect, useState } from 'react';
import { Gauge, WifiOff } from 'lucide-react';
import { api, type ComputeUsage } from './api';

/** The signed-in user's GPU quota and the shared GPU capacity; null while loading. */
export function useComputeUsage(revision = 0, enabled = true) {
  const [usage, setUsage] = useState<ComputeUsage | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    api<ComputeUsage>('/compute/usage')
      .then((row) => {
        if (active) setUsage(row);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [revision, enabled]);
  return usage;
}

/** The cluster is disconnected: no notebook, run or exercise has internet access. */
export function InternetOff() {
  return (
    <span
      className="internet-off"
      title="Arena runs on a disconnected cluster. Code cannot download packages or data."
    >
      <WifiOff size={14} aria-hidden="true" /> Internet: off
    </span>
  );
}

const hours = (value: number) => `${value.toFixed(value < 10 ? 1 : 0)} h`;

export default function GpuUsageMeter({
  usage,
  compact = false,
}: {
  usage: ComputeUsage | null;
  compact?: boolean;
}) {
  if (!usage) return <p className="muted">Loading GPU usage…</p>;
  const percent =
    usage.quota_hours > 0 ? Math.min(100, (usage.used_hours / usage.quota_hours) * 100) : 100;
  const resets = new Date(usage.resets_at).toLocaleString(undefined, {
    weekday: 'long',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  });
  return (
    <section className={`gpu-meter${compact ? ' compact' : ''}`} aria-label="GPU usage this week">
      <div className="gpu-meter-heading">
        <Gauge size={16} aria-hidden="true" />
        <strong>GPU this week</strong>
        <span>
          {hours(usage.used_hours)} of {hours(usage.quota_hours)} used
        </span>
      </div>
      <div
        className="gpu-meter-track"
        role="meter"
        aria-label="GPU hours used this week"
        aria-valuemin={0}
        aria-valuemax={usage.quota_hours}
        aria-valuenow={usage.used_hours}
      >
        <div className={percent >= 90 ? 'high' : undefined} style={{ width: `${percent}%` }} />
      </div>
      <p>
        {hours(usage.remaining_hours)} remaining · resets {resets} UTC
      </p>
      <p>
        GPUs in use across Arena: {usage.in_use} of {usage.capacity}
        {usage.capacity === 0 ? ' (GPU work is disabled)' : ''}
      </p>
      {usage.session_accelerator === 'gpu' ? (
        <p className="gpu-warning" role="status">
          Your GPU session holds a whole GPU, even while idle. Stop it when you finish so others
          can use the card.
        </p>
      ) : (
        !compact && (
          <p className="muted">
            A live GPU session holds the whole card until it stops. Choose CPU unless your code
            needs CUDA, and stop GPU sessions you are not using.
          </p>
        )
      )}
    </section>
  );
}
