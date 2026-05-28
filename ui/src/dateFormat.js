/**
 * European date formatting utilities.
 * All human-visible dates use dd.mm.yyyy format with dots.
 * Internal API payloads use ISO YYYY-MM-DD — convert at render layer only.
 */

function pad(n) {
  return String(n).padStart(2, '0');
}

export function formatDate(iso) {
  if (!iso) return 'Not available';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return 'Not available';
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

export function formatDateTime(iso, includeSeconds = false) {
  if (!iso) return 'Not available';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return 'Not available';
  const date = `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
  const time = includeSeconds
    ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${date} ${time}`;
}

export function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
