import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { getIngestions, getSessionDocuments, getRunDocuments, getDocSpans, reingestDoc, openBootstrapProgress, stopBootstrapSession } from '../../api/client';
import { startBootstrapTracking, stopBootstrapTracking, useBootstrapProgress } from '../../hooks/useBootstrapProgress';
import { formatDateTime, convertLogTimestamps } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';
import DateInput, { todayISO } from '../common/DateInput';

const DOCTYPE_LABEL = {
  drug_approval: 'Drug Approval', guidance: 'Guidance', press_release: 'Press Release',
  safety_alert: 'Safety Alert', reflection_paper: 'Reflection Paper',
  news_item: 'News Item', other: 'Unclassified',
};

function deriveSessionStatus(succeeded, failed, skipped, inflight) {
  if ((inflight || 0) > 0) return 'running';
  if (failed === 0 && succeeded > 0) return 'success';
  if (succeeded === 0 && (skipped || 0) === 0) return 'error';
  return 'partial';
}

function ChevronIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function G3Status({ status }) {
  const label = { success: 'Success', partial: 'Partial', error: 'Error', failed: 'Failed', running: 'Running', pending: 'Pending' }[status] || status;
  return <span className={`g3-status ${status || 'pending'}${status === 'running' ? ' status-pulse' : ''}`}>{label}</span>;
}

function SrcPill({ src }) {
  const map = {
    n8n_rss: ['n8n', 'Scheduled'],
    scheduled: ['n8n', 'Scheduled'],
    bootstrap_ui: ['bootstrap', 'Bootstrap'],
    manual_cli: ['manual', 'Manual'],
    manual: ['manual', 'Manual'],
  };
  const [cls, label] = map[src] || ['manual', src || 'Manual'];
  return <span className={`g2-srcpill ${cls}`}>{label}</span>;
}

function RetryTimeline({ docId, data, loading, error }) {
  if (loading) {
    return (
      <div className="g3-retry-timeline">
        <div className="g3-retry-spinner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: 'spin 0.8s linear infinite' }}>
            <path d="M21 12a9 9 0 11-6.219-8.56" />
          </svg>
          Loading attempt history…
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="g3-retry-timeline">
        <span style={{ color: 'var(--err-text)', fontFamily: 'var(--mono)', fontSize: 11 }}>Could not load attempt history</span>
      </div>
    );
  }
  return (
    <div className="g3-retry-timeline">
      <div className="g3-retry-label">Attempt history</div>
      {(data || []).map((span) => (
        <div key={span.span_id} className="g3-retry-row">
          <span className="g3-retry-num">#{span.attempt}</span>
          <span className="g3-retry-time">{formatDateTime(span.created_at)}</span>
          <G3Status status={span.status} />
          {span.failure_reason && (
            <span className="g3-retry-reason">{span.failure_reason}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function RetryProgressModal({ docId, sessionId, onClose }) {
  const [phase, setPhase] = useState('running');
  const [events, setEvents] = useState([]);
  const esRef = useRef(null);
  const phaseRef = useRef('running');

  // Keep phaseRef in sync so the SSE handler always reads the latest phase
  useEffect(() => { phaseRef.current = phase; }, [phase]);

  useEffect(() => {
    let closed = false;
    const es = openBootstrapProgress(sessionId);
    esRef.current = es;

    // Hard timeout: if still running after 25 min, auto-close.
    // Backend timeout is 1200s (20 min) — 25 min gives a safety margin.
    const hardTimeout = setTimeout(() => {
      if (!closed && phaseRef.current === 'running') {
        setPhase('disconnected');
        es.close();
      }
    }, 25 * 60 * 1000);

    es.onmessage = (ev) => {
      if (closed) return;
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'doc') {
          setEvents((prev) => [...prev, msg]);
          if (msg.status === 'ok') setPhase('done');
          else if (msg.status === 'skipped') setPhase('skipped');
          else setPhase('failed');
          es.close();
        } else if (msg.type === 'progress') {
          if (msg.status !== 'pending' && msg.status !== 'running') {
            setPhase(msg.status === 'success' ? 'done' : 'failed');
            es.close();
          }
        }
      } catch (_) {}
    };
    es.onerror = () => {
      if (!closed) { setPhase('disconnected'); es.close(); }
    };

    return () => {
      closed = true;
      clearTimeout(hardTimeout);
      if (esRef.current) { esRef.current.close(); esRef.current = null; }
    };
  }, [sessionId]);

  const handleStop = async () => {
    stopBootstrapTracking();
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
    try { await stopBootstrapSession(sessionId); } catch (_) {}
    setPhase('failed');
  };

  const phaseStyle = {
    running:      { bg: 'rgba(59,130,246,0.1)', color: 'var(--accent-l)', border: 'rgba(59,130,246,0.3)', label: 'Running…' },
    done:         { bg: 'var(--ok-tint)', color: 'var(--ok-text)', border: 'var(--ok-tint-border)', label: 'Indexed ✓' },
    skipped:      { bg: 'rgba(245,158,11,0.1)', color: '#f59e0b', border: 'rgba(245,158,11,0.3)', label: 'Skipped' },
    failed:       { bg: 'var(--err-tint)', color: 'var(--err-text)', border: 'var(--err-tint-border)', label: 'Failed ✗' },
    disconnected: { bg: 'rgba(245,158,11,0.1)', color: '#f59e0b', border: 'rgba(245,158,11,0.3)', label: 'Connection lost' },
  }[phase] || {};

  return createPortal(
    <div className="rp-modal-backdrop" onClick={onClose}>
      <div className="rp-modal" style={{ width: 540, maxWidth: '92vw' }} onClick={(e) => e.stopPropagation()}>
        <div className="mh">
          <div>
            <h3>Retrying ingestion</h3>
            <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 440 }}>
              {docId}
            </div>
          </div>
          <button className="close" onClick={onClose}>
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 3l8 8M11 3l-8 8"/></svg>
          </button>
        </div>
        <div className="mbody" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontSize: 10.5, fontFamily: 'var(--mono)', fontWeight: 600, letterSpacing: '0.06em',
              textTransform: 'uppercase', padding: '2px 8px', borderRadius: 3,
              background: phaseStyle.bg, color: phaseStyle.color, border: `1px solid ${phaseStyle.border}`,
              animation: phase === 'running' ? 'pulse 1.5s ease-in-out infinite' : 'none',
            }}>
              {phaseStyle.label}
            </span>
            <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>
              session {sessionId.slice(0, 8)}…
            </span>
          </div>

          <div style={{ background: 'var(--doc-bg)', border: '1px solid var(--doc-border)', borderRadius: 4, padding: '8px 10px', minHeight: 60, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {events.length === 0 && phase === 'running' && (
              <span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>
                Waiting for ingestion worker… (this can take 1–3 minutes for large documents)
              </span>
            )}
            {events.map((ev, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <span style={{
                  fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600, padding: '1px 5px', borderRadius: 2, flexShrink: 0, marginTop: 1,
                  background: ev.status === 'ok' ? 'var(--ok-tint)' : ev.status === 'skipped' ? 'rgba(245,158,11,0.1)' : 'var(--err-tint)',
                  color: ev.status === 'ok' ? 'var(--ok-text)' : ev.status === 'skipped' ? '#f59e0b' : 'var(--err-text)',
                  border: `1px solid ${ev.status === 'ok' ? 'var(--ok-tint-border)' : ev.status === 'skipped' ? 'rgba(245,158,11,0.3)' : 'var(--err-tint-border)'}`,
                }}>
                  {ev.status === 'ok' ? 'OK' : ev.status === 'skipped' ? 'SKIP' : 'ERR'}
                </span>
                <div style={{ flex: 1 }}>
                  {ev.status === 'ok' && (
                    <span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--ok-text)' }}>
                      Indexed successfully{ev.chunks != null ? ` — ${ev.chunks} chunks` : ''}
                    </span>
                  )}
                  {ev.reason && (
                    <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: ev.status === 'ok' ? 'var(--doc-text-3)' : 'var(--err-text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5, marginTop: ev.status === 'ok' ? 2 : 0 }}>
                      {ev.reason}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {phase === 'disconnected' && (
              <div style={{ fontSize: 12, fontFamily: 'var(--mono)', color: '#f59e0b', lineHeight: 1.5 }}>
                Connection to the server was lost — the background job may still be running.
                Close this window and re-open the Ingestions row in a few minutes to check the updated status.
              </div>
            )}
          </div>
        </div>
        <div className="mfoot" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--doc-text-3)', fontFamily: 'var(--mono)' }}>
            {phase === 'running' ? 'Progress continues in the status bar' : ''}
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            {phase === 'running' && (
              <button
                className="rp-mbtn ghost"
                onClick={handleStop}
                style={{ color: 'var(--err-text)', borderColor: 'var(--err-text)' }}
              >
                Stop
              </button>
            )}
            <button className="rp-mbtn primary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function DocSubTable({ docs, loadingDocs, expandedDoc, onToggleDoc, expandedRetry, retryDataMap, onToggleRetry }) {
  const [docSort, setDocSort] = useState('errors_first');
  const [reingestStates, setReingestStates] = useState({});
  const [retryModal, setRetryModal] = useState(null);
  const { uiMode: ingestionRunning } = useBootstrapProgress();
  const isIngesting = ingestionRunning === 'running';

  const [retryAllState, setRetryAllState] = useState('idle'); // 'idle' | 'running' | 'done'
  const [retryAllCount, setRetryAllCount] = useState({ done: 0, total: 0 });

  const handleReingest = useCallback((e, docId) => {
    e.stopPropagation();
    setReingestStates((s) => ({ ...s, [docId]: 'starting' }));
    reingestDoc(docId)
      .then(({ session_id }) => {
        setReingestStates((s) => ({ ...s, [docId]: 'idle' }));
        setRetryModal({ docId, sessionId: session_id });
        startBootstrapTracking(session_id);
      })
      .catch((err) => {
        setReingestStates((s) => ({ ...s, [docId]: 'start_failed' }));
        setTimeout(() => setReingestStates((s) => ({ ...s, [docId]: 'idle' })), 5000);
      });
  }, []);

  const handleRetryAll = useCallback(async () => {
    const errorDocs = docs.filter((d) => isErrorStatus(d.ingestion_status));
    if (errorDocs.length === 0 || isIngesting) return;
    setRetryAllState('running');
    setRetryAllCount({ done: 0, total: errorDocs.length });
    for (const d of errorDocs) {
      try {
        const { session_id } = await reingestDoc(d.doc_id);
        startBootstrapTracking(session_id);
      } catch (_) {}
      setRetryAllCount((c) => ({ ...c, done: c.done + 1 }));
    }
    setRetryAllState('done');
    setTimeout(() => setRetryAllState('idle'), 5000);
  }, [docs, isIngesting]);

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
            <th style={{ width: 90 }} />
          </tr>
        </thead>
        <tbody>
          {[1, 2, 3].map((i) => (
            <tr key={i}><td colSpan={7} style={{ padding: '10px 12px' }}>
              <div style={{ height: 12, background: 'var(--doc-hover)', borderRadius: 3, width: `${60 + i * 10}%` }} />
            </td></tr>
          ))}
        </tbody>
      </table>
    );
  }

  const isErrorStatus = (s) => s === 'error' || s === 'failed';
  const errorCount = docs.filter((d) => isErrorStatus(d.ingestion_status)).length;
  const sorted = docSort === 'errors_first' && errorCount > 0
    ? [...docs].sort((a, b) => {
        const aErr = isErrorStatus(a.ingestion_status) ? 0 : 1;
        const bErr = isErrorStatus(b.ingestion_status) ? 0 : 1;
        return aErr - bErr;
      })
    : docs;

  return (
    <>
      {errorCount > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px 4px', borderBottom: '1px solid var(--doc-border)' }}>
          <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--err)', fontWeight: 600 }}>
            {errorCount} error{errorCount !== 1 ? 's' : ''}
          </span>
          <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>
            of {docs.length} documents
          </span>
          <div style={{ flex: 1 }} />
          <button
            onClick={() => setDocSort((s) => s === 'errors_first' ? 'default' : 'errors_first')}
            style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 3, cursor: 'pointer',
              fontFamily: 'var(--mono)',
              background: docSort === 'errors_first' ? 'var(--err-tint)' : 'transparent',
              color: docSort === 'errors_first' ? 'var(--err-text)' : 'var(--doc-text-2)',
              border: `1px solid ${docSort === 'errors_first' ? 'var(--err-tint-border)' : 'var(--doc-border)'}`,
            }}
          >
            {docSort === 'errors_first' ? '↑ Errors first' : 'Default order'}
          </button>
          <button
            disabled={isIngesting || retryAllState === 'running'}
            onClick={handleRetryAll}
            style={{
              fontSize: 11, padding: '2px 10px', borderRadius: 3, cursor: (isIngesting || retryAllState === 'running') ? 'default' : 'pointer',
              fontFamily: 'var(--mono)', fontWeight: 600, whiteSpace: 'nowrap',
              background: 'var(--err-text)', color: '#fff', border: 'none',
              opacity: (isIngesting || retryAllState === 'running') ? 0.5 : 1,
            }}
          >
            {retryAllState === 'running'
              ? `Retrying… ${retryAllCount.done}/${retryAllCount.total}`
              : retryAllState === 'done'
                ? 'Done'
                : isIngesting
                  ? '⏳ Ingestion running'
                  : `↺ Retry all ${errorCount} errors`}
          </button>
        </div>
      )}
      <table className="g3-subtable">
        <thead>
          <tr>
            <th>Document Title</th>
            <th style={{ width: 70 }}>Agency</th>
            <th style={{ width: 110 }}>Doc Type</th>
            <th style={{ width: 130 }}>Ingestion Status</th>
            <th className="num" style={{ width: 70 }}>Chunks</th>
            <th>Failure Reason</th>
            <th style={{ width: 90 }} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((d) => {
            const retryState = retryDataMap[d.doc_id] || {};
            const retryOpen = expandedRetry === d.doc_id;
            const rs = reingestStates[d.doc_id] || 'idle';
            const isError = isErrorStatus(d.ingestion_status);
            const colSpan = 7;
            return (
              <>
                <tr
                  key={d.doc_id}
                  className="docrow"
                  data-testid={`ingestion-doc-row-${d.doc_id}`}
                  onClick={() => onToggleDoc(d.doc_id)}
                >
                  <td>
                    <span className={`g3-docchev ${expandedDoc === d.doc_id ? 'open' : ''}`}><ChevronIcon /></span>
                    <span className="truncate">{d.document_title || d.doc_id}</span>
                    {d.has_retries && (
                      <button
                        className={`g3-retry-badge${retryOpen ? ' open' : ''}`}
                        data-testid={`ingestion-doc-retry-${d.doc_id}`}
                        title="Show attempt history"
                        onClick={(e) => { e.stopPropagation(); onToggleRetry(d.doc_id); }}
                      >
                        {d.retry_count} attempts
                      </button>
                    )}
                  </td>
                  <td><span className="agency-mini">{d.agency || '—'}</span></td>
                  <td className="dim">{DOCTYPE_LABEL[d.doc_type] || d.doc_type || '—'}</td>
                  <td><G3Status status={d.ingestion_status} /></td>
                  <td className="num mono">{d.chunk_count > 0 ? d.chunk_count : '—'}</td>
                  <td style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.45, paddingTop: 6, paddingBottom: 6 }}>
                    {d.failure_reason ? <span className="reason">{d.failure_reason}</span> : <span className="dim">—</span>}
                  </td>
                  <td onClick={(e) => e.stopPropagation()} style={{ paddingRight: 10, textAlign: 'right' }}>
                    {isError && (
                      <button
                        disabled={rs === 'starting' || isIngesting}
                        onClick={(e) => handleReingest(e, d.doc_id)}
                        title={isIngesting ? 'Another ingestion is already running' : undefined}
                        style={{
                          fontSize: 11, padding: '2px 7px', borderRadius: 3,
                          cursor: (rs === 'starting' || isIngesting) ? 'default' : 'pointer',
                          fontFamily: 'var(--mono)', fontWeight: 600, whiteSpace: 'nowrap',
                          background: rs === 'start_failed' ? 'var(--err-tint)' : 'transparent',
                          color: rs === 'start_failed' ? 'var(--err-text)' : 'var(--doc-text-2)',
                          border: `1px solid ${rs === 'start_failed' ? 'var(--err-tint-border)' : 'var(--doc-border)'}`,
                          opacity: (rs === 'starting' || isIngesting) ? 0.6 : 1,
                        }}
                      >
                        {isIngesting ? '⏳ Running' : rs === 'starting' ? '…' : rs === 'start_failed' ? '✗ Failed to start' : '↺ Retry'}
                      </button>
                    )}
                  </td>
                </tr>
                {retryOpen && (
                  <tr className="g3-retry-expand-row" key={`${d.doc_id}-retry`} data-testid={`ingestion-doc-retry-expand-${d.doc_id}`}>
                    <td colSpan={colSpan}>
                      <RetryTimeline
                        docId={d.doc_id}
                        data={retryState.items}
                        loading={retryState.loading}
                        error={retryState.error}
                      />
                    </td>
                  </tr>
                )}
                {expandedDoc === d.doc_id && (
                  <tr className="g3-doc-detail" key={`${d.doc_id}-detail`} data-testid={`ingestion-doc-expand-${d.doc_id}`}>
                    <td colSpan={colSpan}>
                      <div className="inner">
                        <span className="k">Trace ID</span>
                        <span className="v">
                          {d.trace_id
                            ? <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{d.trace_id}</span>
                            : <span className="dim">—</span>}
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
            );
          })}
        </tbody>
      </table>
      {retryModal && (
        <RetryProgressModal
          docId={retryModal.docId}
          sessionId={retryModal.sessionId}
          onClose={() => setRetryModal(null)}
        />
      )}
    </>
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

function useRetryState() {
  const [expandedRetry, setExpandedRetry] = useState(null);
  const [retryDataMap, setRetryDataMap] = useState({});

  const handleToggleRetry = useCallback(async (docId) => {
    if (expandedRetry === docId) {
      setExpandedRetry(null);
      return;
    }
    setExpandedRetry(docId);
    if (retryDataMap[docId]) return;
    setRetryDataMap((m) => ({ ...m, [docId]: { loading: true, items: null, error: null } }));
    try {
      const data = await getDocSpans(docId);
      setRetryDataMap((m) => ({ ...m, [docId]: { loading: false, items: data.items || [], error: null } }));
    } catch {
      setRetryDataMap((m) => ({ ...m, [docId]: { loading: false, items: null, error: true } }));
    }
  }, [expandedRetry, retryDataMap]);

  return { expandedRetry, retryDataMap, handleToggleRetry };
}

function SessionGroupRow({ item, isOpen, onToggle }) {
  const [docs, setDocs] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [docPage, setDocPage] = useState(1);
  const [docPageSize, setDocPageSize] = useState(25);
  const [docTotal, setDocTotal] = useState(0);
  const [expandedDoc, setExpandedDoc] = useState(null);
  const { expandedRetry, retryDataMap, handleToggleRetry } = useRetryState();
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

  const status = item.status || deriveSessionStatus(item.doc_count_succeeded, item.doc_count_failed, item.doc_count_skipped, item.doc_count_inflight);

  return (
    <div className="g3-row session" data-testid={`ingestion-session-group-${item.run_token}`}>
      <div className="g3-row-head" onClick={onToggle} data-testid={`ingestion-session-expand-${item.run_token}`}>
        <span className={`g3-chev ${isOpen ? 'open' : ''}`}><ChevronIcon /></span>
        <span className="g3-cell mono"><span className="lbl">Date</span>{formatDateTime(item.triggered_at)}</span>
        <span className="g3-cell"><span className="lbl">Status</span><G3Status status={status} /></span>
        <span className="g3-cell num"><span className="lbl">New</span>{(item.doc_count_succeeded ?? 0).toLocaleString()}</span>
        <span className="g3-cell num"><span className="lbl">Skipped</span>{item.doc_count_skipped > 0 ? item.doc_count_skipped : '—'}</span>
        <span className={`g3-cell num errnum${item.doc_count_failed > 0 ? ' has' : ''}`}>
          <span className="lbl">Errors</span>{item.doc_count_failed ?? 0}
        </span>
      </div>
      {isOpen && (
        <div className="g3-sub">
          <DocSubTable
            docs={docs}
            loadingDocs={loadingDocs}
            expandedDoc={expandedDoc}
            onToggleDoc={(id) => setExpandedDoc(expandedDoc === id ? null : id)}
            expandedRetry={expandedRetry}
            retryDataMap={retryDataMap}
            onToggleRetry={handleToggleRetry}
          />
          {docTotal > docPageSize && (
            <SubPager page={docPage} pageSize={docPageSize} total={docTotal} onPage={handlePage} onPageSize={handlePageSize} />
          )}
        </div>
      )}
    </div>
  );
}

function IngestionRunRow({ item, isOpen, onToggle }) {
  const [docs, setDocs] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState(null);
  const { expandedRetry, retryDataMap, handleToggleRetry } = useRetryState();
  const fetchedRef = useRef(false);
  const liveRef = useRef(false);
  const isRunning = item.status === 'running';

  // Initial fetch for running runs
  useEffect(() => {
    if (!isRunning) return;
    if (!liveRef.current) {
      liveRef.current = true;
      getRunDocuments(item.run_id, 1, 200)
        .then((data) => { setDocs(data.items || []); })
        .catch(() => {});
    }
  }, [isRunning, item.run_id]);

  // One-time fetch on expand for completed runs
  useEffect(() => {
    if (isRunning) return;
    if (isOpen && !fetchedRef.current) {
      fetchedRef.current = true;
      setLoadingDocs(true);
      getRunDocuments(item.run_id, 1, 50)
        .then((data) => { setDocs(data.items || []); })
        .catch(() => setDocs([]))
        .finally(() => setLoadingDocs(false));
    }
  }, [isOpen, item.run_id, isRunning]);

  // Update status badge and counts from live progress
  const liveStatus = rssState?.progress?.status;
  const displayStatus = isRunning && liveStatus ? liveStatus : item.status;
  const displayNew = isRunning && rssState?.progress?.total > 0 ? rssState.progress.total : item.doc_count_new;
  const displayErrors = isRunning && rssState?.progress?.failed > 0 ? rssState.progress.failed : item.doc_count_errors;

  return (
    <div className="g3-row rss" data-testid={`ingestion-run-row-${item.run_id}`}>
      <div className="g3-row-head" onClick={onToggle} data-testid={`ingestion-run-expand-${item.run_id}`}>
        <span className={`g3-chev ${isOpen ? 'open' : ''}`}><ChevronIcon /></span>
        <span className="g3-cell mono"><span className="lbl">Date</span>{formatDateTime(item.triggered_at)}</span>
        <span className="g3-cell"><span className="lbl">Status</span><G3Status status={displayStatus} /></span>
        <span className="g3-cell num"><span className="lbl">New</span>{displayNew ?? '—'}</span>
        <span className="g3-cell num"><span className="lbl">Skipped</span>{item.doc_count_skipped ?? '—'}</span>
        <span className={`g3-cell num errnum${displayErrors > 0 ? ' has' : ''}`}>
          <span className="lbl">Errors</span>{displayErrors ?? 0}
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
              {convertLogTimestamps(item.error_detail)}
            </div>
          )}
          <DocSubTable
            docs={docs}
            loadingDocs={loadingDocs}
            expandedDoc={expandedDoc}
            onToggleDoc={(id) => setExpandedDoc(expandedDoc === id ? null : id)}
            expandedRetry={expandedRetry}
            retryDataMap={retryDataMap}
            onToggleRetry={handleToggleRetry}
          />
        </div>
      )}
    </div>
  );
}

function isoToEu(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-');
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

function DateRangeFilter({ dateFrom, dateTo, onApply }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(dateFrom || todayISO());
  const [to, setTo] = useState(dateTo || todayISO());
  const ref = useRef(null);
  const active = !!(dateFrom || dateTo);

  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (open) {
      setFrom(dateFrom || todayISO());
      setTo(dateTo || todayISO());
    }
  }, [open, dateFrom, dateTo]);

  function handleApply() { onApply(from, to); setOpen(false); }
  function handleClear() { onApply('', ''); setOpen(false); }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Filter by date range"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          height: 34, padding: '0 11px',
          background: active ? 'var(--accent-tint)' : 'var(--doc-surface)',
          border: `1px solid ${active ? 'var(--accent-l)' : 'var(--doc-border)'}`,
          borderRadius: 5, cursor: 'pointer',
          color: active ? 'var(--accent-l)' : 'var(--doc-text-2)',
          fontSize: 12,
        }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        {active ? `${isoToEu(dateFrom) || '…'} → ${isoToEu(dateTo) || '…'}` : 'Date range'}
      </button>
      {open && (
        <div className="rp-popover" style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, padding: '12px 14px' }}>
          <div className="rp-popover-section-lbl">Date range</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--doc-text-2)' }}>
              From (dd.mm.yyyy)
              <DateInput value={from} onChange={setFrom} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--doc-text-2)' }}>
              To (dd.mm.yyyy)
              <DateInput value={to} onChange={setTo} />
            </label>
          </div>
          <div className="rp-date-actions">
            <button className="rp-date-apply" onClick={handleApply}>Apply</button>
            {(from || to) && (
              <button className="rp-date-clear" onClick={handleClear}>Clear</button>
            )}
          </div>
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
        <DateRangeFilter
          dateFrom={dateFrom}
          dateTo={dateTo}
          onApply={(from, to) => { setDateFrom(from); setDateTo(to); }}
        />
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
            const key = item.type === 'session_group' ? `sess-${item.run_token}` : `run-${item.run_id}`;
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
              <IngestionRunRow
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
