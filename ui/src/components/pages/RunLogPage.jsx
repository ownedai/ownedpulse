import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { createPortal } from 'react-dom';
import { getFeedRuns, getFeedRunDetail } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';

function useClickOutside(ref, handler) {
  useEffect(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) handler();
    }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [ref, handler]);
}

function FilterDropdown({ options, value, onChange }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useClickOutside(popRef, () => { if (open) setOpen(false); });
  const current = options.find((o) => o.value === value) || options[0];

  function handleOpen() {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left });
    }
    setOpen((v) => !v);
  }

  return (
    <>
      <button ref={btnRef} className={`rp-dropdown-btn${open ? ' open' : ''}`} onClick={handleOpen} style={{ fontSize: 12.5 }}>
        <span>{current.label}</span>
        <svg width="9" height="9" viewBox="0 0 10 6" fill="currentColor"><path d="M0 0l5 6 5-6z"/></svg>
      </button>
      {open && createPortal(
        <div ref={popRef} className="rp-popover" style={{ position: 'fixed', top: pos.top, left: pos.left, minWidth: 150 }}>
          {options.map((o) => (
            <div key={o.label} className={`rp-popover-item${value === o.value ? ' active' : ''}`} onClick={() => { onChange(o.value); setOpen(false); }}>
              {o.label}
            </div>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}

function SourceBadge({ source }) {
  const isManual = source === 'manual';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      padding: '2px 7px', borderRadius: 3,
      background: isManual ? 'var(--accent-l)' : 'transparent',
      color: isManual ? '#fff' : 'var(--doc-text-2)',
      border: isManual ? 'none' : '1px solid var(--doc-border)',
    }}>
      {isManual && <span style={{ width: 5, height: 5, borderRadius: 3, background: '#fff' }} />}
      {source || '—'}
    </span>
  );
}

function StatusBadge({ status }) {
  const c = getStatusConfig(status);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      padding: '2px 7px', borderRadius: 3,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: 3, background: c.dot, flexShrink: 0,
        animation: c.pulse ? 'pulse 1.5s infinite' : 'none',
      }} />
      {c.label}
    </span>
  );
}

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

  useEffect(() => {
    if (initialRun) toggleExpand(initialRun);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.ceil(total / pageSize);
  const uniqueFeeds = [...new Set(runs.map((r) => r.feed_source).filter(Boolean))].sort();
  const feedOptions = [{ label: 'All feeds', value: null }, ...uniqueFeeds.map((f) => ({ label: f, value: f }))];
  const statusOptions = [
    { label: 'All statuses', value: null },
    { label: 'Success', value: 'success' },
    { label: 'Running', value: 'running' },
    { label: 'Error', value: 'error' },
  ];

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Feed Run Log</h1>
        </div>
      </div>

      <div className="rp-table-wrap">
        <div className="rp-filter-strip">
          <FilterDropdown options={statusOptions} value={statusFilter} onChange={(v) => { setStatusFilter(v); setPage(1); }} />
          <FilterDropdown options={feedOptions} value={feedFilter} onChange={(v) => { setFeedFilter(v); setPage(1); }} />
          <div style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
            {total.toLocaleString()} runs
          </span>
          <button
            onClick={fetchData}
            style={{ width: 28, height: 28, background: 'transparent', border: '1px solid var(--doc-border)', borderRadius: 3, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--doc-text-2)' }}
            title="Refresh"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
          </button>
        </div>

        <table className="rp-table">
          <thead>
            <tr>
              <th style={{ width: 160 }}>Triggered At ↓</th>
              <th style={{ width: 90 }}>Source</th>
              <th style={{ width: 140 }}>Feed</th>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 50 }}>New</th>
              <th style={{ width: 60 }}>Skipped</th>
              <th style={{ width: 60 }}>Errors</th>
              <th style={{ width: 80 }}>Duration</th>
              <th style={{ width: 120 }}>N8N ID</th>
            </tr>
          </thead>
          <tbody>
            {loading && runs.length === 0 && (
              <tr><td colSpan={9} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>Loading...</td></tr>
            )}
            {!loading && runs.length === 0 && (
              <tr><td colSpan={9} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>No feed runs found.</td></tr>
            )}
            {runs.map((run) => (
              <>
                <tr key={run.run_id} onClick={() => toggleExpand(run.run_id)} style={{ cursor: 'pointer' }}>
                  <td className="mono" style={{ fontSize: 11 }}>{formatDateTime(run.triggered_at)}</td>
                  <td><SourceBadge source={run.trigger_source} /></td>
                  <td className="mono" style={{ fontSize: 11 }}>{run.feed_source || '—'}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td className="mono">{run.items_new}</td>
                  <td className="mono">{run.items_skipped}</td>
                  <td className="mono" style={{ color: run.error_count > 0 ? 'var(--err)' : undefined }}>{run.error_count}</td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {run.duration_ms != null ? `${(run.duration_ms / 1000).toFixed(1)}s` : '—'}
                  </td>
                  <td className="mono" style={{ fontSize: 10 }}>
                    {run.n8n_execution_id ? (
                      <span style={{ color: 'var(--accent-l)' }}>
                        {run.n8n_execution_id.length > 12 ? run.n8n_execution_id.substring(0, 12) + '…' : run.n8n_execution_id}
                        {' '}↗
                      </span>
                    ) : '—'}
                  </td>
                </tr>
                {expandedRun === run.run_id && (
                  <tr key={`${run.run_id}-exp`}>
                    <td colSpan={9} style={{ padding: '16px 24px', background: 'var(--doc-bg)' }}>
                      {detailLoading ? (
                        <span style={{ color: 'var(--doc-text-2)', fontSize: 13 }}>Loading...</span>
                      ) : runDetail ? (
                        <div>
                          <div style={{ fontSize: 12, marginBottom: 12, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)' }}>
                            Run: {runDetail.run.run_id}
                            {runDetail.run.error_detail && (
                              <div style={{ marginTop: 8, padding: 8, background: 'var(--err-tint)', borderRadius: 4, color: 'var(--err-text)', fontSize: 12 }}>
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
                                  <th style={{ width: 90 }}>Status</th>
                                </tr>
                              </thead>
                              <tbody>
                                {runDetail.documents.map((d) => (
                                  <tr key={d.document_id}>
                                    <td>
                                      <Link to={`/corpus/${d.document_id}`} style={{ color: 'var(--accent-l)', fontSize: 13 }}>
                                        {d.document_title}
                                      </Link>
                                    </td>
                                    <td className="mono" style={{ fontSize: 11 }}>{d.document_type || '—'}</td>
                                    <td className="mono" style={{ fontSize: 11 }}>{formatDate(d.publication_date)}</td>
                                    <td className="mono">{d.ingestion_status === 'pending' ? '—' : d.chunk_count}</td>
                                    <td><StatusBadge status={d.ingestion_status} /></td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          ) : (
                            <span style={{ color: 'var(--doc-text-3)', fontSize: 13, fontStyle: 'italic' }}>No new documents in this run.</span>
                          )}
                        </div>
                      ) : (
                        <span style={{ color: 'var(--doc-text-3)', fontSize: 13 }}>Failed to load run detail.</span>
                      )}
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div className="rp-pager">
            <span>{((page - 1) * pageSize) + 1}–{Math.min(page * pageSize, total)} of {total.toLocaleString()}</span>
            <div className="pages">
              <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>&larr;</button>
              <button onClick={() => setPage(page + 1)} disabled={page >= totalPages}>&rarr;</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
