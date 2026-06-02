export const STATUS_CONFIG = {
  success:  { label: 'SUCCESS',  color: 'var(--ok)',      bg: 'var(--ok-tint)',     border: 'var(--ok-tint-border)',    dot: 'var(--ok)',      pulse: false },
  partial:  { label: 'PARTIAL',  color: 'var(--warn)',    bg: 'var(--warn-tint)',   border: 'var(--warn-tint-border)',  dot: 'var(--warn)',    pulse: false },
  failed:   { label: 'FAILED',   color: 'var(--err-text)',bg: 'var(--err-tint)',    border: 'var(--err-tint-border)',   dot: 'var(--err)',     pulse: false },
  error:    { label: 'ERROR',    color: 'var(--err-text)',bg: 'var(--err-tint)',    border: 'var(--err-tint-border)',   dot: 'var(--err)',     pulse: false },
  running:  { label: 'RUNNING',  color: 'var(--accent-l)',bg: 'var(--accent-tint)', border: 'var(--accent-tint-deep)', dot: 'var(--accent-l)',pulse: true  },
  pending:  { label: 'PENDING',  color: 'var(--doc-text-3)', bg: 'var(--doc-bg)', border: 'var(--doc-border)',         dot: 'var(--doc-text-3)', pulse: false },
  indexed:  { label: 'INDEXED',  color: 'var(--ok)',      bg: 'var(--ok-tint)',     border: 'var(--ok-tint-border)',   dot: 'var(--ok)',      pulse: false },
  complete: { label: 'SUCCESS',  color: 'var(--ok)',      bg: 'var(--ok-tint)',     border: 'var(--ok-tint-border)',   dot: 'var(--ok)',      pulse: false },
};

export function getStatusConfig(status) {
  return STATUS_CONFIG[status?.toLowerCase()] ?? STATUS_CONFIG['error'];
}
