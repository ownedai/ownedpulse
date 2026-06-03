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

export function exportHistory() {
  return fetch(`${API_BASE}/api/query/history/export`).then(r => {
    if (!r.ok) throw new Error(`History export failed: ${r.status}`);
    return r.text();
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
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/api/corpus/documents?${qs.toString()}`);
}

export function getHealth() {
  return request('/api/health');
}

// ── Corpus routes ────────────────────────────────────────────────────────────

export function getCorpusDocumentsV2(params) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/api/corpus/documents?${qs.toString()}`);
}

export function getDocumentDetail(docId) {
  return request(`/api/corpus/documents/${encodeURIComponent(docId)}`);
}

export function getDocumentChunks(docId, page = 1, pageSize = 50) {
  return request(`/api/corpus/documents/${encodeURIComponent(docId)}/chunks?page=${page}&page_size=${pageSize}`);
}

export function getFeedRuns(params) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/api/corpus/feed-runs?${qs.toString()}`);
}

export function getFeedRunDetail(runId) {
  return request(`/api/corpus/feed-runs/${encodeURIComponent(runId)}`);
}

export function getSupersedeChain(familyId) {
  return request(`/api/corpus/supersede/${encodeURIComponent(familyId)}`);
}

// ── Admin routes ─────────────────────────────────────────────────────────────

export function getAdminHealth() {
  return request('/api/admin/health');
}

export function getAdminFeeds() {
  return request('/api/admin/feeds');
}

export function toggleFeed(feedId, enabled) {
  return request(`/api/admin/feeds/${encodeURIComponent(feedId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });
}

export function triggerPipelineRun() {
  return request('/api/admin/trigger-run', { method: 'POST' });
}

export function getSchedulerStatus() {
  return request('/api/admin/scheduler/status');
}

export function triggerSchedulerNow() {
  return request('/api/admin/scheduler/trigger', { method: 'POST' });
}

export function pauseScheduler() {
  return request('/api/admin/scheduler/pause', { method: 'POST' });
}

export function resumeScheduler() {
  return request('/api/admin/scheduler/resume', { method: 'POST' });
}

export function getSchedulerConfig() {
  return request('/api/admin/scheduler/config');
}

export function updateSchedulerConfig(hour, minute, timezone) {
  return request('/api/admin/scheduler/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hour, minute, timezone }),
  });
}

export function triggerFeedRun(feedId) {
  return request(`/api/admin/feeds/${encodeURIComponent(feedId)}/trigger`, { method: 'POST' });
}

export function getAdminModels() {
  return request('/api/admin/models');
}

export function updateActiveModel(model) {
  return request('/api/admin/model', {
    method: 'PUT',
    body: JSON.stringify({ model }),
  });
}

// ── Bootstrap / Sources routes ────────────────────────────────────────────────

export function getBootstrapState() {
  return request('/api/bootstrap/state');
}

export function getCorpusSummary() {
  return request('/api/bootstrap/corpus-summary');
}

export function startBootstrapRun(scope, force = false) {
  return request('/api/bootstrap/run', {
    method: 'POST',
    body: JSON.stringify({ scope, force }),
  });
}

export function activateRss() {
  return request('/api/bootstrap/activate-rss', { method: 'POST' });
}

export function reingestDoc(docId) {
  return request('/api/bootstrap/reingest-doc', {
    method: 'POST',
    body: JSON.stringify({ doc_id: docId }),
  });
}

export function openBootstrapProgress(sessionId) {
  return new EventSource(`${API_BASE}/api/bootstrap/progress/${sessionId}`);
}

// ── Ingestions routes ─────────────────────────────────────────────────────────

export function getIngestions(params = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/api/ingestions?${qs.toString()}`);
}

export function getSessionDocuments(runToken, page = 1, pageSize = 25) {
  return request(`/api/ingestions/sessions/${encodeURIComponent(runToken)}/documents?page=${page}&page_size=${pageSize}`);
}

export function getRunDocuments(runId, page = 1, pageSize = 25) {
  return request(`/api/ingestions/runs/${encodeURIComponent(runId)}/documents?page=${page}&page_size=${pageSize}`);
}
