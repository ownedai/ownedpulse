const API_BASE = import.meta.env.VITE_API_URL || '';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export function submitQuery(body, signal) {
  return request('/api/query', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
}

export function getQuery(queryId) {
  return request(`/api/query/${queryId}`);
}

export function getQueryHistory(limit = 10, offset = 0) {
  return request(`/api/query/history?limit=${limit}&offset=${offset}`);
}

export function exportQuery(queryId, format = 'json') {
  const url = `${API_BASE}/api/query/${queryId}/export?format=${format}`;
  return fetch(url).then(r => {
    if (!r.ok) throw new Error(`Export failed: ${r.status}`);
    return format === 'json' ? r.json() : r.blob();
  });
}

export function exportHistory(format = 'json') {
  const url = `${API_BASE}/api/query/history/export?format=${format}`;
  return fetch(url).then(r => {
    if (!r.ok) throw new Error(`History export failed: ${r.status}`);
    return format === 'json' ? r.json() : r.blob();
  });
}

export function getTrace(traceId) {
  return request(`/api/trace/${traceId}`);
}

export function getPdfPage(filePath, pageNo) {
  return `/api/pdf/page?file_path=${encodeURIComponent(filePath)}&page_no=${pageNo}`;
}

export function getPdfInfo(filePath) {
  return request(`/api/pdf/info?file_path=${encodeURIComponent(filePath)}`);
}

export function getCorpusStats() {
  return request('/api/corpus/stats');
}

export function getCorpusDocuments(params) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, v); });
  return request(`/api/corpus/documents?${qs.toString()}`);
}

export function getHealth() {
  return request('/api/health');
}
