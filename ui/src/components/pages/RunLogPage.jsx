import { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getFeedRuns, getFeedRunDetail } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

const STATUS_COLORS = {
  running: { bg: '#3b82f6', pulse: true },
  complete: { bg: '#22c55e' },
  error: { bg: '#ef4444' },
};

export default function RunLogPage() {
  const [searchParams] = useSearchParams();
  const initialRun = searchParams.get('run');
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState(null);
  const [feedFilter, setFeedFilter] = useState(null);
  const [expandedRun, setExpandedRun] = useState(initialRun || null);
  const [runDetail, setRunDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const pageSize = 30;

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = { page, page_size: pageSize };
    if (statusFilter) params.status = statusFilter;
    if (feedFilter) params.feed_source = feedFilter;
    getFeedRuns(params)
      .then((data) => {
        setRuns(data.items || []);
        setTotal(data.total || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page, statusFilter, feedFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleExpand = (runId) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      setRunDetail(null);
      return;
    }
    setExpandedRun(runId);
    setDetailLoading(true);
    getFeedRunDetail(runId)
      .then(setRunDetail)
      .catch(() => setRunDetail(null))
      .finally(() => setDetailLoading(false));
  };

  const totalPages = Math.ceil(total / pageSize);
  const uniqueFeeds = [...new Set(runs.map((r) => r.feed_source).filter(Boolean))].sort();

  // Auto-expand run from URL param
  useEffect(() => {
    if (initialRun) toggleExpand(initialRun);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Feed Run Log</h1>
          <p>Pipeline execution history.</p>
        </div>
      </div>

      <div className="rp-table-wrap">
        {/* Filters */}
        <div className="rp-filter-strip">
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>Status:</span>
          {[null, 'running', 'complete', 'error'].map((s) => (
            <button
              key={s || 'all'}
              className={`pill${statusFilter === s ? ' on' : ''}`}
              onClick={() => { setStatusFilter(s); setPage(1); }}
              style={{
                fontFamily: 'var(--sans)',
                fontSize: 12.5,
                padding: '5px 11px',
                borderRadius: 3,
                cursor: 'pointer',
                background: statusFilter === s ? 'var(--accent-l)' : 'transparent',
                color: statusFilter === s ? '#fff' : 'var(--doc-text-2)',
                border: statusFilter === s ? '1px solid var(--accent-l)' : '1px solid transparent',
              }}
            >
              {s ? s.charAt(0).toUpperCase() + s.slice(1) : 'All'}
            </button>
          ))}
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)', marginLeft: 12 }}>Feed:</span>
          {[{ label: 'All', value: null }, ...uniqueFeeds.map((f) => ({ label: f, value: f }))].map((f) => (
            <button
              key={f.value || 'all'}
              className={`pill${feedFilter === f.value ? ' on' : ''}`}
              onClick={() => { setFeedFilter(f.value); setPage(1); }}
              style={{
                fontFamily: 'var(--mono)',
                fontSize: 11,
                padding: '3px 8px',
                borderRadius: 3,
                cursor: 'pointer',
                background: feedFilter === f.value ? 'var(--accent-l)' : 'transparent',
                color: feedFilter === f.value ? '#fff' : 'var(--doc-text-2)',
                border: feedFilter === f.value ? '1px solid var(--accent-l)' : '1px solid transparent',
              }}
            >
              {f.label}
            </button>
          ))}
          <div className="spacer" style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
            {total.toLocaleString()} runs
          </span>
        </div>

        <table className="rp-table">
          <thead>
            <tr>
              <th style={{ width: 160 }}>Triggered At</th>
              <th style={{ width: 80 }}>Source</th>
              <th style={{ width: 140 }}>Feed</th>
              <th style={{ width: 80 }}>Status</th>
              <th style={{ width: 60 }}>New</th>
              <th style={{ width: 60 }}>Skipped</th>
              <th style={{ width: 60 }}>Errors</th>
              <th style={{ width: 80 }}>Duration</th>
            </tr>
          </thead>
          <tbody>
            {loading && runs.length === 0 && (
              <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>Loading...</td></tr>
            )}
            {!loading && runs.length === 0 && (
              <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>No feed runs found.</td></tr>
            )}
            {runs.map((run) => {
              const sc = STATUS_COLORS[run.status] || { bg: '#64748b' };
              return (
                <>
                  <tr
                    key={run.run_id}
                    onClick={() => toggleExpand(run.run_id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="mono" style={{ fontSize: 11 }}>{formatDateTime(run.triggered_at)}</td>
                    <td>
                      <span className="status" style={{
                        background: run.trigger_source === 'manual' ? 'var(--accent-l)' : 'transparent',
                        color: run.trigger_source === 'manual' ? '#fff' : 'var(--doc-text)',
                        border: run.trigger_source === 'manual' ? 'none' : '1px solid var(--doc-border)',
                        padding: '2px 8px',
                        borderRadius: 3,
                        fontSize: 11,
                      }}>
                        {run.trigger_source}
                      </span>
                    </td>
                    <td className="mono" style={{ fontSize: 11 }}>{run.feed_source || '—'}</td>
                    <td>
                      <span style={{
                        display: 'inline-block',
                        width: 8, height: 8, borderRadius: 4,
                        background: sc.bg,
                        marginRight: 6,
                        animation: sc.pulse ? 'pulse 1.5s infinite' : 'none',
                      }} />
                      {run.status}
                    </td>
                    <td className="mono">{run.items_new}</td>
                    <td className="mono">{run.items_skipped}</td>
                    <td className="mono" style={{ color: run.error_count > 0 ? '#ef4444' : undefined }}>
                      {run.error_count}
                    </td>
                    <td className="mono" style={{ fontSize: 11 }}>
                      {run.duration_ms != null ? `${(run.duration_ms / 1000).toFixed(1)}s` : '—'}
                    </td>
                  </tr>
                  {expandedRun === run.run_id && (
                    <tr key={`${run.run_id}-exp`}>
                      <td colSpan={8} style={{ padding: '16px 24px', background: 'var(--doc-bg)' }}>
                        {detailLoading ? (
                          <span style={{ color: 'var(--doc-text-2)', fontSize: 13 }}>Loading...</span>
                        ) : runDetail ? (
                          <div>
                            <div style={{ fontSize: 13, marginBottom: 12, color: 'var(--doc-text-2)' }}>
                              <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>Run ID: {runDetail.run.run_id}</span>
                              {runDetail.run.n8n_execution_id && (
                                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, marginLeft: 16 }}>
                                  n8n: {runDetail.run.n8n_execution_id}
                                </span>
                              )}
                              {runDetail.run.error_detail && (
                                <div style={{ marginTop: 8, padding: 8, background: '#fef2f2', borderRadius: 4, color: '#991b1b', fontSize: 12 }}>
                                  {runDetail.run.error_detail}
                                </div>
                              )}
                            </div>
                            {runDetail.documents && runDetail.documents.length > 0 ? (
                              <table className="rp-table" style={{ margin: 0 }}>
                                <thead>
                                  <tr>
                                    <th>Document</th>
                                    <th style={{ width: 120 }}>Doc Type</th>
                                    <th style={{ width: 100 }}>Date</th>
                                    <th style={{ width: 60 }}>Chunks</th>
                                    <th style={{ width: 80 }}>Status</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {runDetail.documents.map((d) => (
                                    <tr key={d.document_id}>
                                      <td>
                                        <Link
                                          to={`/corpus/${d.document_id}`}
                                          style={{ color: 'var(--accent-l)', fontSize: 13 }}
                                        >
                                          {d.document_title}
                                        </Link>
                                      </td>
                                      <td className="mono" style={{ fontSize: 11 }}>{d.document_type || '—'}</td>
                                      <td className="mono" style={{ fontSize: 11 }}>{formatDate(d.publication_date)}</td>
                                      <td className="mono">{d.chunk_count}</td>
                                      <td>
                                        <span className={`status ${d.ingestion_status === 'indexed' || d.ingestion_status === 'success' ? 'ok' : 'warn'}`}>
                                          {d.ingestion_status}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            ) : (
                              <span style={{ color: 'var(--doc-text-3)', fontSize: 13 }}>No documents ingested in this run.</span>
                            )}
                          </div>
                        ) : (
                          <span style={{ color: 'var(--doc-text-3)', fontSize: 13 }}>Failed to load run detail.</span>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div className="rp-pager">
            <span>{((page - 1) * pageSize) + 1}–{Math.min(page * pageSize, total)} of {total.toLocaleString()}</span>
            <div className="pages">
              <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>
                &larr;
              </button>
              <button onClick={() => setPage(page + 1)} disabled={page >= totalPages}>
                &rarr;
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
