import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import {
  getCorpusSummary, getBootstrapState,
  startBootstrapRun, activateRss,
  getAdminFeeds, toggleFeed,
  getCorpusDocumentsV2, reingestDoc,
  openBootstrapProgress,
} from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';

// ── Icons ─────────────────────────────────────────────────────────────────────

const RefreshIcon = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M13.5 5.5A6 6 0 1 0 14 8"/><path d="M14 2.5V6h-3.5"/>
  </svg>
);

const WarnIcon = () => (
  <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 2L1.5 13.5h13z"/><path d="M8 6.5v3.5"/>
    <circle cx="8" cy="11.6" r="0.4" fill="currentColor" stroke="none"/>
  </svg>
);

const CheckIcon = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 8.5l3.2 3.2L13 5"/>
  </svg>
);

const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
    <path d="M3 3l8 8M11 3l-8 8"/>
  </svg>
);

// ── Corpus Summary Card ───────────────────────────────────────────────────────

const DOC_TYPE_LABELS = {
  guidance_pdf: 'Guidance',
  press_release: 'Press Releases',
  reflection_paper: 'Reflection Papers',
  drug_approval: 'Drug Approvals',
  safety_alert: 'Safety Alerts',
  news_item: 'News',
  other: 'Other',
};

function CorpusSummaryCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCorpusSummary()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const agencies = ['FDA', 'EMA', 'ICH'];

  return (
    <div className="rp-src-card">
      <div className="rp-src-card-lbl">Corpus Summary</div>
      {loading ? (
        <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)', padding: '8px 0' }}>Loading…</div>
      ) : (
        <div className="rp-corpus-summary">
          {agencies.map((agency) => {
            const ag = data?.agencies?.find((a) => a.agency === agency);
            const byType = ag?.by_type || {};
            const total = ag?.total || 0;
            const topTypes = Object.entries(byType)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3);

            return (
              <div key={agency} className="rp-agency-group">
                <div className="ag-head">
                  <Link
                    to={`/corpus?agency=${agency}`}
                    className="ag-name"
                    style={{ textDecoration: 'none', color: 'inherit' }}
                  >{agency}</Link>
                  <Link
                    to={`/corpus?agency=${agency}`}
                    className="ag-total"
                    style={{ textDecoration: 'none' }}
                  >{total.toLocaleString()} docs</Link>
                </div>
                {topTypes.map(([type, count]) => (
                  <Link
                    key={type}
                    to={`/corpus?agency=${agency}&doc_type=${type}`}
                    className="ag-row"
                    style={{ textDecoration: 'none', display: 'flex' }}
                  >
                    <span className="cls">{DOC_TYPE_LABELS[type] || type}</span>
                    <span className={`n ${count === 0 ? 'zero' : ''}`}>{count}</span>
                  </Link>
                ))}
                {topTypes.length === 0 && (
                  <div className="ag-row">
                    <span className="cls" style={{ fontStyle: 'italic', color: 'var(--doc-text-3)' }}>No data</span>
                    <span className="n zero">0</span>
                  </div>
                )}
                <div className="ag-foot">
                  Last indexed <span className="v">{ag?.last_indexed ? formatDateTime(ag.last_indexed) : (data?.last_indexed ? formatDateTime(data.last_indexed) : '—')}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Base Corpus Card ──────────────────────────────────────────────────────────

function BaseCorpusCard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reingesting, setReingesting] = useState(null);

  const fetch = useCallback(() => {
    setLoading(true);
    getCorpusDocumentsV2({ page: 1, page_size: 20, doc_type: 'guidance' })
      .then((d) => setItems(d.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  async function handleReingest(docId) {
    setReingesting(docId);
    try {
      await reingestDoc(docId);
    } catch (_) {}
    setTimeout(() => {
      setReingesting(null);
      fetch();
    }, 3000);
  }

  return (
    <div className="rp-src-card">
      <div className="rp-src-card-lbl">
        <span>Base Corpus</span>
        <button
          onClick={fetch}
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--doc-text-2)', display: 'flex', alignItems: 'center' }}
          title="Refresh"
        >
          <RefreshIcon />
        </button>
      </div>
      <table className="rp-table" style={{ fontSize: 12.5 }}>
        <thead>
          <tr>
            <th>Document</th>
            <th style={{ width: 60 }}>Agency</th>
            <th style={{ width: 80 }}>Version</th>
            <th style={{ width: 100 }}>Published</th>
            <th style={{ width: 90 }}>Status</th>
            <th style={{ width: 60, textAlign: 'right' }}>Chunks</th>
            <th style={{ width: 110 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>Loading…</td></tr>
          )}
          {!loading && items.length === 0 && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>No documents found.</td></tr>
          )}
          {items.map((doc) => (
            <tr key={doc.document_id}>
              <td>
                <span
                  className="truncate"
                  title={doc.document_title}
                  style={{ maxWidth: 320, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5, color: 'var(--doc-text)' }}
                >
                  {doc.document_title || doc.document_id}
                </span>
              </td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>{doc.issuing_body}</td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.document_version || '—'}</td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{formatDate(doc.publication_date)}</td>
              <td>
                <StatusBadge status={doc.ingestion_status} />
              </td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.chunk_count || '—'}</td>
              <td>
                <div className="rp-act">
                  {reingesting === doc.document_id ? (
                    <span className="btn busy"><span className="sp" /> Reingesting…</span>
                  ) : (
                    <button className="btn" onClick={() => handleReingest(doc.document_id)}>
                      <RefreshIcon /> Reingest
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }) {
  const c = getStatusConfig(status);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      padding: '2px 7px', borderRadius: 2,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: 3, background: c.dot, flexShrink: 0 }} />
      {c.label}
    </span>
  );
}

// ── RSS Feeds Card ────────────────────────────────────────────────────────────

function RssFeedsCard() {
  const [feeds, setFeeds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(null);
  const [reingesting, setReingesting] = useState(null);

  const fetchFeeds = useCallback(() => {
    setLoading(true);
    getAdminFeeds()
      .then(setFeeds)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchFeeds(); }, [fetchFeeds]);

  async function handleToggle(feedId, current) {
    setToggling(feedId);
    try {
      await toggleFeed(feedId, !current);
      setFeeds((prev) => prev.map((f) => f.feed_id === feedId ? { ...f, enabled: !current } : f));
    } catch (_) {}
    setToggling(null);
  }

  return (
    <div className="rp-src-card">
      <div className="rp-src-card-lbl">
        <span>RSS Feeds</span>
        <button
          onClick={fetchFeeds}
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--doc-text-2)', display: 'flex', alignItems: 'center' }}
          title="Refresh"
        >
          <RefreshIcon />
        </button>
      </div>
      <table className="rp-table" style={{ fontSize: 12.5 }}>
        <thead>
          <tr>
            <th>Feed Name</th>
            <th style={{ width: 80 }}>Source ID</th>
            <th>URL</th>
            <th style={{ width: 70 }}>Enabled</th>
            <th style={{ width: 130 }}>Last Fetch</th>
            <th style={{ width: 90 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr><td colSpan={6} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>Loading…</td></tr>
          )}
          {!loading && feeds.length === 0 && (
            <tr><td colSpan={6} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>No feeds configured.</td></tr>
          )}
          {feeds.map((f) => (
            <tr key={f.feed_id}>
              <td style={{ fontWeight: 500 }}>{f.name}</td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>{f.feed_id}</td>
              <td>
                <span
                  title={f.url}
                  style={{ display: 'block', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)', cursor: 'help' }}
                >
                  {f.url}
                </span>
              </td>
              <td>
                <button
                  className={`rp-toggle ${f.enabled ? 'on' : ''} ${toggling === f.feed_id ? 'loading' : ''}`}
                  onClick={() => handleToggle(f.feed_id, f.enabled)}
                  disabled={toggling === f.feed_id}
                  title={f.enabled ? 'Click to disable' : 'Click to enable'}
                >
                  <span className="thumb" />
                </button>
              </td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
                {f.last_run_at ? formatDateTime(f.last_run_at) : '—'}
              </td>
              <td>
                <div className="rp-act">
                  {reingesting === f.feed_id ? (
                    <span className="btn busy"><span className="sp" /> Running…</span>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Initial Load Card + Modal ─────────────────────────────────────────────────

const SCOPE_GROUPS = [
  {
    agency: 'FDA',
    rows: [
      { key: 'fda_guidance', label: 'Guidance documents', hint: 'PDF guidance, Q&A, technical specs' },
      { key: 'fda_press', label: 'Press releases', hint: 'News and announcements' },
    ],
  },
  {
    agency: 'EMA',
    rows: [
      { key: 'ema', label: 'All EMA documents', hint: 'Guidelines, reflection papers, annexes' },
    ],
  },
  {
    agency: 'ICH',
    rows: [
      { key: 'ich', label: 'All ICH guidelines', hint: 'Quality, safety, efficacy guidelines' },
    ],
  },
];

function InitialLoadModal({ onClose, lastBootstrap, docCount }) {
  const isInitialized = docCount > 0;
  const [mode, setMode] = useState('config'); // config | running | complete
  const [confirmed, setConfirmed] = useState(false);
  const [scope, setScope] = useState({ fda_guidance: true, fda_press: true, ema: true, ich: true });
  const [progress, setProgress] = useState({ total: 0, processed: 0, succeeded: 0, failed: 0, status: 'pending' });
  const [docEvents, setDocEvents] = useState([]);
  const [rssActivated, setRssActivated] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const esRef = useRef(null);

  function toggleScope(key) {
    setScope((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleStart() {
    try {
      const result = await startBootstrapRun(scope, isInitialized);
      setSessionId(result.session_id);
      setProgress({ total: result.total_docs, processed: 0, succeeded: 0, failed: 0, status: 'running' });
      setMode('running');

      // Open SSE stream
      const es = openBootstrapProgress(result.session_id);
      esRef.current = es;

      es.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (data.type === 'doc') {
            setDocEvents((prev) => [data, ...prev].slice(0, 100));
          } else if (data.type === 'progress') {
            setProgress(data);
            if (data.status !== 'pending' && data.status !== 'running') {
              es.close();
              esRef.current = null;
              setMode('complete');
              // Try to activate RSS
              activateRss().then((r) => {
                if (r.activated || r.already_active) setRssActivated(true);
              }).catch(() => {});
            }
          }
        } catch (_) {}
      };

      es.onerror = () => {
        if (esRef.current) {
          es.close();
          esRef.current = null;
        }
      };
    } catch (err) {
      alert(err.message || 'Failed to start bootstrap');
    }
  }

  function handleClose() {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    onClose();
  }

  const canClose = mode !== 'running';
  const pct = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
  const hasPartial = progress.failed > 0 && progress.succeeded > 0;
  const hasAllFailed = progress.failed > 0 && progress.succeeded === 0;

  return createPortal(
    <div className="rp-modal-backdrop" onClick={canClose ? handleClose : undefined}>
      <div className="rp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mh">
          <h3>{mode === 'config' ? 'Configure Initial Load' : 'Initial Load'}</h3>
          <button
            className={`close ${!canClose ? 'disabled' : ''}`}
            onClick={canClose ? handleClose : undefined}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="mbody">
          {mode === 'config' && (
            <>
              {isInitialized && (
                <div className="rp-wipe-warn">
                  <span className="ico"><WarnIcon /></span>
                  <div className="wtxt">
                    <b>This will wipe and reingest the entire corpus.</b> All existing chunks, ingestion history, and Langfuse traces for the selected scope will be replaced. This cannot be undone.
                  </div>
                </div>
              )}
              {isInitialized && (
                <label className="rp-wipe-check" onClick={() => setConfirmed((c) => !c)}>
                  <span className={`rp-check warn ${confirmed ? 'on' : ''}`}>
                    {confirmed && <CheckIcon />}
                  </span>
                  <span className="ctxt">I understand this will wipe and reingest the selected corpus</span>
                </label>
              )}

              <div style={{ marginTop: isInitialized ? 12 : 0 }}>
                {SCOPE_GROUPS.map((g) => (
                  <div key={g.agency} className="rp-scope-group" style={{ marginTop: 10 }}>
                    <div className="grp-name">{g.agency}</div>
                    {g.rows.map((r) => (
                      <div key={r.key} className="rp-check-row" onClick={() => toggleScope(r.key)}>
                        <span className={`rp-check ${scope[r.key] ? 'on' : ''}`}>
                          {scope[r.key] && <CheckIcon />}
                        </span>
                        <span className="cls">{r.label}</span>
                        <span className="cnt" style={{ color: 'var(--doc-text-3)', fontStyle: 'italic', fontSize: 11 }}>{r.hint}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>

              <div className="rp-modal-note">
                The selected document classes will be fetched from their sources and reingested. This run will appear in Run Log with full trace provenance.
              </div>
            </>
          )}

          {(mode === 'running' || mode === 'complete') && (
            <>
              <div className="rp-prog-head">
                {mode === 'running' ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, fontFamily: 'var(--mono)', letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 500, padding: '2px 8px', borderRadius: 2, background: 'var(--info-tint, #eff6ff)', color: 'var(--accent-l)', border: '1px solid var(--info-tint-border, #bfdbfe)', animation: 'pulse 1.5s ease-in-out infinite' }}>
                    Running
                  </span>
                ) : (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, fontFamily: 'var(--mono)', letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 500, padding: '2px 8px', borderRadius: 2, background: hasAllFailed ? 'var(--err-tint)' : hasPartial ? 'var(--warn-tint)' : 'var(--ok-tint)', color: hasAllFailed ? 'var(--err-text)' : hasPartial ? 'var(--warn-text)' : 'var(--ok-text)', border: `1px solid ${hasAllFailed ? 'var(--err-tint-border)' : hasPartial ? 'var(--warn-tint-border)' : 'var(--ok-tint-border)'}` }}>
                    {hasAllFailed ? 'Failed' : hasPartial ? 'Completed with errors' : 'Complete'}
                  </span>
                )}
                {sessionId && (
                  <span className="run-id">session {sessionId.slice(0, 8)}…</span>
                )}
              </div>

              <div className="rp-counter">
                <div className="ctop">
                  <span className="lead">
                    Processing <span className="v">{progress.processed}</span> / {progress.total}
                  </span>
                  <span className="pct">{pct}%</span>
                </div>
                <div className="track">
                  <div className="fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="tally">
                  <span className="ok">Succeeded <b>{progress.succeeded}</b></span>
                  <span className="fail">Failed <b>{progress.failed}</b></span>
                </div>
              </div>

              {docEvents.length > 0 && (
                <div className="rp-doc-stream">
                  {docEvents.map((d, i) => (
                    <div key={i} className="drow">
                      <div className="main">
                        <div className="dtitle">{d.doc_id}</div>
                        {d.status === 'failed' && d.reason && (
                          <div className="reason">{d.reason}</div>
                        )}
                        {d.status === 'ok' && (
                          <div className="dmeta">{d.chunks} chunk{d.chunks !== 1 ? 's' : ''}</div>
                        )}
                      </div>
                      <span className="pill">
                        <span className={`rp-pill-sm ${d.status === 'ok' ? 'ok' : 'fail'}`}>
                          {d.status === 'ok' ? 'Success' : 'Failed'}
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {mode === 'complete' && (
                <div className={`rp-prog-summary ${hasAllFailed || hasPartial ? 'warn' : ''}`}>
                  {progress.succeeded} succeeded · {progress.failed} failed
                  {(hasAllFailed || hasPartial) && ' — check Run Log for details'}
                  {rssActivated && (
                    <div className="auto">
                      <span style={{ color: 'var(--ok-text)' }}>●</span> RSS automation: active
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="mfoot">
          {mode === 'config' && (
            <>
              <button className="rp-mbtn ghost" onClick={handleClose}>Cancel</button>
              <button
                className={`rp-mbtn primary ${isInitialized && !confirmed ? 'disabled' : ''}`}
                onClick={isInitialized && !confirmed ? undefined : handleStart}
                disabled={isInitialized && !confirmed}
              >
                Start Initial Load
              </button>
            </>
          )}
          {mode === 'running' && (
            <button className="rp-mbtn ghost disabled" style={{ opacity: 0.4, cursor: 'not-allowed' }}>
              Close (disabled during run)
            </button>
          )}
          {mode === 'complete' && (
            <button className="rp-mbtn primary" onClick={handleClose}>Close</button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

function InitialLoadCard({ onOpenModal, lastBootstrap, docCount, bootstrapDocCount }) {
  return (
    <div className="rp-src-card">
      <div className="rp-src-card-lbl">Initial Load</div>
      <div className="rp-il-row">
        <button className="rp-btn-outline" onClick={onOpenModal}>
          <RefreshIcon />
          {docCount > 0 ? 'Re-run Initial Load' : 'Run Initial Load'}
        </button>
        <div className="rp-il-meta">
          {docCount > 0 ? (
            <>
              Corpus last populated: <span className="v">{lastBootstrap ? formatDateTime(lastBootstrap) : '—'}</span>
              {' · '}
              <span className="v">{(bootstrapDocCount || 0).toLocaleString()}</span> documents loaded in initial run
            </>
          ) : (
            'Corpus is empty. Run Initial Load to ingest all regulatory documents.'
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SourcesPage() {
  const [showModal, setShowModal] = useState(false);
  const [bootstrapState, setBootstrapState] = useState({ doc_count: 0, bootstrap_doc_count: 0, last_bootstrap: null });

  useEffect(() => {
    getBootstrapState()
      .then(setBootstrapState)
      .catch(() => {});
  }, []);

  return (
    <div className="rp-sources-page">
      <div className="rp-sources-inner">
        <CorpusSummaryCard />
        <BaseCorpusCard />
        <RssFeedsCard />
        <InitialLoadCard
          onOpenModal={() => setShowModal(true)}
          lastBootstrap={bootstrapState.last_bootstrap}
          docCount={bootstrapState.doc_count}
          bootstrapDocCount={bootstrapState.bootstrap_doc_count}
        />
      </div>

      {showModal && (
        <InitialLoadModal
          onClose={() => {
            setShowModal(false);
            // Refresh bootstrap state after modal closes
            getBootstrapState().then(setBootstrapState).catch(() => {});
          }}
          lastBootstrap={bootstrapState.last_bootstrap}
          docCount={bootstrapState.doc_count}
        />
      )}
    </div>
  );
}
