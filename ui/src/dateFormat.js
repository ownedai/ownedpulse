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

export function isFutureDate(iso) {
  if (!iso) return false;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return false;
  return d > new Date();
}

// Convert Python logging UTC timestamps (YYYY-MM-DD HH:MM:SS,mmm) to local time
export function convertLogTimestamps(text) {
  if (!text) return text;
  return text.replace(/(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),(\d+)/g, (match, date, time, ms) => {
    const d = new Date(`${date}T${time}Z`);
    if (isNaN(d.getTime())) return match;
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())},${ms}`;
  });
}
