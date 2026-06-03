import { useState, useEffect, useCallback, useRef } from 'react';
import { getIngestions, getSessionDocuments, getRunDocuments, getRunInfo } from '../../api/client';
import { formatDateTime } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';

const DOCTYPE_LABEL = {
  drug_approval: 'Drug Approval', guidance: 'Guidance', press_release: 'Press Release',
  safety_alert: 'Safety Alert', reflection_paper: 'Reflection Paper',
  news_item: 'News Item', other: 'Unclassified',
};

function deriveSessionStatus(succeeded, failed) {
  if (failed === 0) return 'success';
  if (succeeded === 0) return 'error';
  return 'partial';
}

function ChevronIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function TraceViewer({ traceId }) {
  const [state, setState] = useState('idle'); // idle | loading | loaded | error
  const [data, setData] = useState(null);

  const load = async () => {
    if (state === 'loading') return;
    setState('loading');
    try {
      const d = await getRunInfo(traceId);
      setData(d);
      setState('loaded');
    } catch {
      setState('error');
    }
  };

  if (state === 'idle') {
    return <button className="g3-trace-btn" onClick={load}>View Run</button>;
  }
  if (state === 'loading') {
    return <span className="g3-trace-loading">Loading…</span>;
  }
  if (state === 'error') {
    return <span className="g3-trace-err">Run info unavailable</span>;
  }

  const fields = [
    ['Trigger', data.trigger_source],
    ['Feed', data.feed_source || '—'],
    ['Status', data.status],
    ['Started', data.triggered_at ? formatDateTime(data.triggered_at) : '—'],
    ['Duration', data.duration_ms != null ? `${data.duration_ms} ms` : '—'],
    ['New', data.items_new],
    ['Skipped', data.items_skipped],
    ['Errors', data.error_count],
  ];

  return (
    <div className="g3-trace-inline">
      <div className="g3-trace-strip">
        {fields.map(([k, v], i) => (
          <span key={k} className="g3-trace-field">
            <span className="g3-trace-fk">{k}</span>
            <span className="g3-trace-fv">{v}</span>
          </span>
        ))}
        <button className="g3-trace-close" onClick={() => setState('idle')}>✕</button>
      </div>
      {data.error_detail && (
        <div className="g3-trace-err-row">
          <span className="g3-trace-fk">Error</span>
          <span className="g3-trace-fv err">{data.error_detail}</span>
        </div>
      )}
    </div>
  );
}

function G3Status({ status }) {
  const label = { success: 'Success', partial: 'Partial', error: 'Error', running: 'Running', pending: 'Pending' }[status] || status;
  return <span className={`g3-status ${status || 'pending'}${status === 'running' ? ' status-pulse' : ''}`}>{label}</span>;
}

function SrcPill({ src }) {
  const isScheduled = src === 'n8n_rss' || src === 'scheduled';
  return <span className="g2-srcpill src">{isScheduled ? 'Scheduled' : 'Manual'}</span>;
}

function DocSubTable({ docs, loadingDocs, expandedDoc, onToggleDoc }) {
  if (loadingDocs) {
    return (
      <table className="g3-subtable">
        <thead>
          <tr>
            <th>Document Title</th>
            <th style={{ width: 70 }}>Agency</th>
            <th style={{ width: 110 }}>Doc Type</th>
            <th style={{ width: 130 }}>Ingestion Status</th>
            <th className="num" style={{ width: 70 }}>Chunks</th>
            <th>Failure Reason</th>
          </tr>
        </thead>
        <tbody>
          {[1, 2, 3].map((i) => (
            <tr key={i}><td colSpan={6} style={{ padding: '10px 12px' }}>
              <div style={{ height: 12, background: 'var(--doc-hover)', borderRadius: 3, width: `${60 + i * 10}%` }} />
            </td></tr>
          ))}
        </tbody>
      </table>
    );
  }

  return (
    <table className="g3-subtable">
      <thead>
        <tr>
          <th>Document Title</th>
          <th style={{ width: 70 }}>Agency</th>
          <th style={{ width: 110 }}>Doc Type</th>
          <th style={{ width: 130 }}>Ingestion Status</th>
          <th className="num" style={{ width: 70 }}>Chunks</th>
          <th>Failure Reason</th>
        </tr>
      </thead>
      <tbody>
        {docs.map((d) => (
          <>
            <tr
              key={d.doc_id}
              className="docrow"
              data-testid={`ingestion-doc-row-${d.doc_id}`}
              onClick={() => onToggleDoc(d.doc_id)}
            >
              <td>
                <span className={`g3-docchev ${expandedDoc === d.doc_id ? 'open' : ''}`}><ChevronIcon /></span>
                <span className="truncate" style={{ display: 'inline', maxWidth: 320 }}>{d.document_title || d.doc_id}</span>
              </td>
              <td><span className="agency-mini">{d.agency || '—'}</span></td>
              <td className="dim">{DOCTYPE_LABEL[d.doc_type] || d.doc_type || '—'}</td>
              <td><G3Status status={d.ingestion_status} /></td>
              <td className="num mono">{d.chunk_count > 0 ? d.chunk_count : '—'}</td>
              <td>{d.failure_reason ? <span className="reason truncate">{d.failure_reason}</span> : <span className="dim">—</span>}</td>
            </tr>
            {expandedDoc === d.doc_id && (
              <tr className="g3-doc-detail" key={`${d.doc_id}-detail`} data-testid={`ingestion-doc-expand-${d.doc_id}`}>
                <td colSpan={6}>
                  <div className="inner">
                    <span className="k">Trace ID</span>
                    <span className="v">
                      {d.trace_id ? (
                        <>
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{d.trace_id.slice(0, 16)}…</span>
                          <TraceViewer traceId={d.trace_id} />
                        </>
                      ) : <span className="dim">—</span>}
                    </span>
                    <span className="k">Source URL</span>
                    <span className="v">
                      {d.source_url ? <a href={d.source_url} target="_blank" rel="noreferrer">{d.source_url}</a> : '—'}
                    </span>
                    <span className="k">Fetched at</span>
                    <span className="v">{formatDateTime(d.fetched_at) || '—'}</span>
                    <span className="k">Parsed at</span>
                    <span className="v">{formatDateTime(d.parsed_at) || '—'}</span>
                    <span className="k">Embedding</span>
                    <span className="v">{d.embedding_model || '—'}</span>
                    <span className="k">Chunks</span>
                    <span className="v">{d.chunk_count || 0}</span>
                  </div>
                </td>
              </tr>
            )}
          </>
        ))}
      </tbody>
    </table>
  );
}

function SubPager({ page, pageSize, total, onPage, onPageSize }) {
  const totalPages = Math.ceil(total / pageSize);
  return (
    <div className="g3-sub-pager">
      <div className="g3-pager">
        <span className="size">
          Rows:
          <span className="seg" data-testid="pagination-size-select">
            {[25, 50, 100].map((s) => (
              <button key={s} className={pageSize === s ? 'on' : ''} onClick={() => onPageSize(s)}>{s}</button>
            ))}
          </span>
        </span>
        <span style={{ color: 'var(--doc-text-3)' }}>
          Showing {Math.min((page - 1) * pageSize + 1, total)}–{Math.min(page * pageSize, total)} of {total.toLocaleString()} docs
        </span>
        <span className="nav">
          <button
            className={page === 1 ? 'disabled' : ''}
            data-testid="pagination-prev"
            onClick={() => page > 1 && onPage(page - 1)}
          >‹ Prev</button>
          {totalPages > 0 && Array.from({ length: Math.min(totalPages, 5) }, (_, i) => i + 1).map((p) => (
            <button key={p} className={p === page ? 'on' : ''} onClick={() => onPage(p)}>{p}</button>
          ))}
          {totalPages > 5 && <button className="disabled">…</button>}
          <button
            className={page >= totalPages ? 'disabled' : ''}
            data-testid="pagination-next"
            onClick={() => page < totalPages && onPage(page + 1)}
          >Next ›</button>
        </span>
      </div>
    </div>
  );
}

function SessionGroupRow({ item, isOpen, onToggle }) {
  const [docs, setDocs] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [docPage, setDocPage] = useState(1);
  const [docPageSize, setDocPageSize] = useState(25);
  const [docTotal, setDocTotal] = useState(0);
  const [expandedDoc, setExpandedDoc] = useState(null);
  const fetchedRef = useRef(false);

  const fetchDocs = useCallback(async (page, pageSize) => {
    setLoadingDocs(true);
    try {
      const data = await getSessionDocuments(item.run_token, page, pageSize);
      setDocs(data.items || []);
      setDocTotal(data.total || 0);
    } catch (e) {
      setDocs([]);
    } finally {
      setLoadingDocs(false);
    }
  }, [item.run_token]);

  useEffect(() => {
    if (isOpen && !fetchedRef.current) {
      fetchedRef.current = true;
      fetchDocs(1, docPageSize);
    }
  }, [isOpen, fetchDocs, docPageSize]);

  const handlePage = (p) => { setDocPage(p); fetchDocs(p, docPageSize); };
  const handlePageSize = (s) => { setDocPageSize(s); setDocPage(1); fetchDocs(1, s); };

  const status = deriveSessionStatus(item.doc_count_succeeded, item.doc_count_failed);

  return (
    <div className="g3-row session" data-testid={`ingestion-session-group-${item.run_token}`}>
      <div className="g3-row-head" onClick={onToggle}>
        <span className={`g3-chev ${isOpen ? 'open' : ''}`}><ChevronIcon /></span>
        <span className="g3-cell mono"><span className="lbl">Triggered At</span>{formatDateTime(item.triggered_at)}</span>
        <span className="g3-cell"><span className="lbl">Source</span><SrcPill src={item.source} /></span>
        <span className="g3-cell dim"><span className="lbl">Feed</span><span className="g3-feed">all</span></span>
        <span className="g3-cell"><span className="lbl">Status</span><G3Status status={status} /></span>
        <span className="g3-cell num"><span className="lbl">New</span>{item.doc_count ?? '—'}</span>
        <span className="g3-cell num dim"><span className="lbl">Skipped</span>—</span>
        <span className={`g3-cell num errnum${item.doc_count_failed > 0 ? ' has' : ''}`}>
          <span className="lbl">Errors</span>{item.doc_count_failed ?? '—'}
        </span>
        <span className="g3-cell num dim"><span className="lbl">Duration</span>—</span>
      </div>
      {isOpen && (
        <div className="g3-sub">
          <DocSubTable
            docs={docs}
            loadingDocs={loadingDocs}
            expandedDoc={expandedDoc}
            onToggleDoc={(id) => setExpandedDoc(expandedDoc === id ? null : id)}
          />
          {docTotal > docPageSize && (
            <SubPager page={docPage} pageSize={docPageSize} total={docTotal} onPage={handlePage} onPageSize={handlePageSize} />
          )}
        </div>
      )}
    </div>
  );
}

function RssRunRow({ item, isOpen, onToggle }) {
  const [docs, setDocs] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (isOpen && !fetchedRef.current) {
      fetchedRef.current = true;
      setLoadingDocs(true);
      getRunDocuments(item.run_id, 1, 50)
        .then((data) => { setDocs(data.items || []); })
        .catch(() => setDocs([]))
        .finally(() => setLoadingDocs(false));
    }
  }, [isOpen, item.run_id]);

  return (
    <div className="g3-row rss" data-testid={`ingestion-run-row-${item.run_id}`}>
      <div className="g3-row-head" onClick={onToggle}>
        <span className={`g3-chev ${isOpen ? 'open' : ''}`}><ChevronIcon /></span>
        <span className="g3-cell mono"><span className="lbl">Triggered At</span>{formatDateTime(item.triggered_at)}</span>
        <span className="g3-cell"><span className="lbl">Source</span><SrcPill src={item.source} /></span>
        <span className="g3-cell"><span className="lbl">Feed</span><span className="g3-feed">{item.feed_name || '—'}</span></span>
        <span className="g3-cell"><span className="lbl">Status</span><G3Status status={item.status} /></span>
        <span className="g3-cell num"><span className="lbl">New</span>{item.doc_count_new ?? '—'}</span>
        <span className="g3-cell num"><span className="lbl">Skipped</span>{item.doc_count_skipped ?? '—'}</span>
        <span className={`g3-cell num errnum${item.doc_count_errors > 0 ? ' has' : ''}`}>
          <span className="lbl">Errors</span>{item.doc_count_errors ?? 0}
        </span>
        <span className="g3-cell num dim">
          <span className="lbl">Duration</span>{item.duration_seconds != null ? `${item.duration_seconds}s` : '—'}
        </span>
      </div>
      {isOpen && (
        <div className="g3-sub">
          {item.error_detail && (
            <div style={{
              margin: '10px 12px 4px', padding: '10px 14px', borderRadius: 4,
              background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)',
              color: 'var(--err-text)', fontFamily: 'var(--mono)', fontSize: 11.5,
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6,
            }}>
              <div style={{ fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 600, marginBottom: 6, opacity: 0.7 }}>Error detail</div>
              {item.error_detail}
            </div>
          )}
          <DocSubTable
            docs={docs}
            loadingDocs={loadingDocs}
            expandedDoc={expandedDoc}
            onToggleDoc={(id) => setExpandedDoc(expandedDoc === id ? null : id)}
          />
        </div>
      )}
    </div>
  );
}

function FilterDropdown({ label, value, options, onChange, testId }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const current = options.find((o) => o.value === value) || options[0];

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <div className="dd" data-testid={testId} onClick={() => setOpen((o) => !o)}>
        {current.label}
        <span className="chev">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </span>
      </div>
      {open && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 4, background: 'var(--doc-surface)', border: '1px solid var(--doc-border)', borderRadius: 5, zIndex: 50, minWidth: 140, boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }}>
          {options.map((o) => (
            <div
              key={o.value}
              onClick={() => { onChange(o.value); setOpen(false); }}
              style={{
                padding: '7px 12px', fontSize: 12.5, cursor: 'pointer', color: o.value === value ? 'var(--accent-l)' : 'var(--doc-text)',
                background: o.value === value ? 'var(--accent-tint)' : 'transparent',
              }}
            >
              {o.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'success', label: 'Success' },
  { value: 'partial', label: 'Partial' },
  { value: 'error', label: 'Error' },
  { value: 'running', label: 'Running' },
];

const SOURCE_OPTIONS = [
  { value: '', label: 'All sources' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'manual', label: 'Manual' },
];

export default function IngestionsPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [openRows, setOpenRows] = useState({});
  const [statusFilter, setStatusFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const load = useCallback(async (p = 1) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getIngestions({
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page: p,
        page_size: pageSize,
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      setError(e.message || 'Failed to load ingestions');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, sourceFilter, dateFrom, dateTo, pageSize]);

  useEffect(() => { setPage(1); load(1); }, [statusFilter, sourceFilter, dateFrom, dateTo, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(page); }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePageSize = (s) => { setPageSize(s); setPage(1); };

  const toggleRow = (key) => setOpenRows((o) => ({ ...o, [key]: !o[key] }));

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="g3">
      <div className="g3-filters">
        <FilterDropdown
          label="All statuses"
          value={statusFilter}
          options={STATUS_OPTIONS}
          onChange={setStatusFilter}
          testId="ingestions-filter-status"
        />
        <FilterDropdown
          label="All sources"
          value={sourceFilter}
          options={SOURCE_OPTIONS}
          onChange={setSourceFilter}
          testId="ingestions-filter-source"
        />
        <div className="date-input">
          <span className="k">from</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </div>
        <div className="date-input">
          <span className="k">to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
        <span className="count-right">
          <span className="v">{total.toLocaleString()}</span> entries
        </span>
      </div>

      {error && (
        <div style={{ margin: '16px 32px', padding: '12px 16px', background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 5, color: 'var(--err-text)', fontSize: 13 }}>
          {error}
        </div>
      )}

      {loading && !items.length ? (
        <div className="g3-list-scroll">
          {[1, 2, 3].map((i) => (
            <div key={i} className="g3-row" style={{ padding: '14px 16px' }}>
              <div style={{ height: 14, background: 'var(--doc-hover)', borderRadius: 3, width: `${40 + i * 15}%` }} />
            </div>
          ))}
        </div>
      ) : !items.length && !loading ? (
        <div className="g3-empty">No ingestion records match the current filters.</div>
      ) : (
        <div className="g3-list-scroll">
          {items.map((item) => {
            const key = item.type === 'session_group' ? `sess-${item.run_token}` : `rss-${item.run_id}`;
            if (item.type === 'session_group') {
              return (
                <SessionGroupRow
                  key={key}
                  item={item}
                  isOpen={!!openRows[key]}
                  onToggle={() => toggleRow(key)}
                />
              );
            }
            return (
              <RssRunRow
                key={key}
                item={item}
                isOpen={!!openRows[key]}
                onToggle={() => toggleRow(key)}
              />
            );
          })}

          {total > 0 && (
            <div className="g3-pager" style={{ paddingTop: 16 }}>
              <span className="size">
                Rows:
                <span className="seg">
                  {[25, 50, 100].map((s) => (
                    <button key={s} className={pageSize === s ? 'on' : ''} onClick={() => handlePageSize(s)}>{s}</button>
                  ))}
                </span>
              </span>
              <span style={{ color: 'var(--doc-text-3)' }}>
                {Math.min((page - 1) * pageSize + 1, total)}–{Math.min(page * pageSize, total)} of {total.toLocaleString()}
              </span>
              <span className="nav">
                <button className={page === 1 ? 'disabled' : ''} onClick={() => page > 1 && setPage((p) => p - 1)}>‹ Prev</button>
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  const p = totalPages <= 7 ? i + 1
                    : page <= 4 ? i + 1
                    : page >= totalPages - 3 ? totalPages - 6 + i
                    : page - 3 + i;
                  return (
                    <button key={p} className={p === page ? 'on' : ''} onClick={() => setPage(p)}>{p}</button>
                  );
                })}
                {totalPages > 7 && page < totalPages - 3 && <button className="disabled">…</button>}
                <button className={page >= totalPages ? 'disabled' : ''} onClick={() => page < totalPages && setPage((p) => p + 1)}>Next ›</button>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
