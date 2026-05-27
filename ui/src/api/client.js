const API_BASE = import.meta.env.VITE_API_URL || '';

export async function submitQuery(query, filters) {
  const res = await fetch(`${API_BASE}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, filters }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Server responded with ${res.status}`);
  }
  return res.json();
}

export async function fetchHistory() {
  const res = await fetch(`${API_BASE}/api/query/history`);
  if (!res.ok) throw new Error('Failed to fetch history');
  return res.json();
}

export async function fetchCorpusStats() {
  const res = await fetch(`${API_BASE}/api/corpus/stats`);
  if (!res.ok) throw new Error('Failed to fetch corpus stats');
  return res.json();
}

export async function fetchPdfPage(filePath, pageNumber) {
  const url = `${API_BASE}/api/pdf/page?file_path=${encodeURIComponent(filePath)}&page_number=${pageNumber}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('PDF page not available');
  return res.blob();
}
