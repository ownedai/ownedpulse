import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { formatDate } from '../dateFormat';
import { getBootstrapStatus, getDateEstimate, postSourcesBootstrap } from '../api/client';

// ── Icons ─────────────────────────────────────────────────────────────────────

const CloseIcon = () => (
  <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
    <path d="M3 3l8 8M11 3l-8 8"/>
  </svg>
);

const CheckIcon = () => (
  <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 8.5l3.2 3.2L13 5"/>
  </svg>
);

const WarnIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 1 }}>
    <path d="M8 2L1.5 13.5h13z"/><path d="M8 6.5v3.5"/>
    <circle cx="8" cy="11.6" r="0.4" fill="currentColor" stroke="none"/>
  </svg>
);

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children, badge }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
      <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--doc-text-3)', fontWeight: 600 }}>
        {children}
      </span>
      {badge !== undefined && (
        <span style={{ fontSize: 10, fontFamily: 'var(--mono)', padding: '1px 6px', borderRadius: 10, background: 'var(--doc-bg)', border: '1px solid var(--doc-border)', color: 'var(--doc-text-2)' }}>
          {badge}
        </span>
      )}
    </div>
  );
}

const AGENCY_STYLE = {
  FDA: { background: 'rgba(59,130,246,0.12)', color: '#3b82f6' },
  EMA: { background: 'rgba(16,185,129,0.12)', color: '#10b981' },
  ICH: { background: 'rgba(139,92,246,0.12)', color: '#8b5cf6' },
};

function AgencyBadge({ agency }) {
  const s = AGENCY_STYLE[agency] || { background: 'var(--doc-bg)', color: 'var(--doc-text-2)' };
  return (
    <span style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600, letterSpacing: '0.06em', padding: '2px 6px', borderRadius: 2, flexShrink: 0, ...s }}>
      {agency}
    </span>
  );
}

function StatusDot({ status }) {
  const color = status === 'indexed' || status === 'success' ? 'var(--ok, #22c55e)'
    : status === 'superseded' ? 'var(--warn, #f59e0b)'
    : 'var(--doc-text-3)';
  return (
    <span style={{ width: 6, height: 6, borderRadius: 3, background: color, flexShrink: 0 }} title={status} />
  );
}

// ── Date window helpers ───────────────────────────────────────────────────────

const DATE_WINDOW_OPTIONS = [
  { value: '1year',  label: '1 year' },
  { value: '3years', label: '3 years' },
  { value: '5years', label: '5 years' },
  { value: 'all',    label: 'All available' },
  { value: 'custom', label: 'Custom' },
];

function getDateRange(dateWindow, customFromYear, customToYear) {
  const thisYear = new Date().getFullYear();
  if (dateWindow === '1year')  return { date_from: `${thisYear - 1}-01-01`, date_to: null };
  if (dateWindow === '3years') return { date_from: `${thisYear - 3}-01-01`, date_to: null };
  if (dateWindow === '5years') return { date_from: `${thisYear - 5}-01-01`, date_to: null };
  if (dateWindow === 'all')    return { date_from: null, date_to: null };
  if (dateWindow === 'custom') return { date_from: `${customFromYear}-01-01`, date_to: `${customToYear}-12-31` };
  return { date_from: null, date_to: null };
}

// ── Main component ────────────────────────────────────────────────────────────

export default function BootstrapModal({ onClose, onStarted }) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [bootstrapStatus, setBootstrapStatus] = useState(null);

  const [selectedBaseCorpus, setSelectedBaseCorpus] = useState([]);
  const [selectedFeeds, setSelectedFeeds]           = useState([]);
  const [dateWindow, setDateWindow]                 = useState('3years');
  const [customFromYear, setCustomFromYear]         = useState(new Date().getFullYear() - 5);
  const [customToYear, setCustomToYear]             = useState(new Date().getFullYear());
  const [sourceMode, setSourceMode]                 = useState('changed_only');
  const [confirmed, setConfirmed]                   = useState(false);
  const [estimate, setEstimate]                     = useState(null);
  const [submitting, setSubmitting]                 = useState(false);
  const [submitError, setSubmitError]               = useState(null);

  const estimateAbortRef   = useRef(null);
  const estimateTimeoutRef = useRef(null);

  // Load bootstrap status on mount
  useEffect(() => {
    getBootstrapStatus()
      .then(data => {
        setBootstrapStatus(data);
        setSelectedBaseCorpus(data.base_corpus.map(d => d.document_id));
        setSelectedFeeds(data.rss_feeds.map(f => f.feed_id));
      })
      .catch(err => setLoadError(err.message || 'Failed to load corpus status'))
      .finally(() => setLoading(false));
  }, []);

  // Refresh estimate whenever selection or date window changes
  const refreshEstimate = useCallback(() => {
    if (estimateTimeoutRef.current) clearTimeout(estimateTimeoutRef.current);
    estimateTimeoutRef.current = setTimeout(() => {
      if (estimateAbortRef.current) estimateAbortRef.current.abort();
      if (selectedFeeds.length === 0) {
        setEstimate({ estimated_docs: 0, estimated_chunks: 0, note: '' });
        return;
      }
      const ctrl = new AbortController();
      estimateAbortRef.current = ctrl;
      const { date_from, date_to } = getDateRange(dateWindow, customFromYear, customToYear);
      getDateEstimate(selectedFeeds, date_from, date_to, ctrl.signal)
        .then(data => { if (!ctrl.signal.aborted) setEstimate(data); })
        .catch(() => {});
    }, 300);
  }, [selectedFeeds, dateWindow, customFromYear, customToYear]);

  useEffect(() => {
    if (!loading) refreshEstimate();
  }, [selectedFeeds, dateWindow, customFromYear, customToYear, loading, refreshEstimate]);

  // Cleanup on unmount
  useEffect(() => () => {
    if (estimateTimeoutRef.current) clearTimeout(estimateTimeoutRef.current);
    if (estimateAbortRef.current) estimateAbortRef.current.abort();
  }, []);

  async function handleSubmit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const { date_from, date_to } = getDateRange(dateWindow, customFromYear, customToYear);
      const payload = {
        mode: sourceMode === 'changed_only' ? 'reload_changed_only' : 'wipe_and_reload',
        base_corpus: selectedBaseCorpus,
        rss_feeds: selectedFeeds.map(feed_id => ({ feed_id, date_from, date_to })),
      };
      const result = await postSourcesBootstrap(payload);
      onStarted?.(result);
      onClose();
    } catch (err) {
      setSubmitError(err.message || 'Failed to start bootstrap');
      setSubmitting(false);
    }
  }

  // Derive year range for custom dropdowns from actual feed date_min values
  const feedDateMin = bootstrapStatus?.rss_feeds
    ?.filter(f => selectedFeeds.includes(f.feed_id) && f.date_min)
    ?.reduce((min, f) => (!min || f.date_min < min ? f.date_min : min), null);
  const minYear = feedDateMin ? parseInt(feedDateMin.slice(0, 4)) : new Date().getFullYear() - 30;
  const maxYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: maxYear - minYear + 1 }, (_, i) => minYear + i);

  const canSubmit = confirmed && !submitting && !loading;
  const rssEstimate = estimate?.estimated_docs ?? null;
  const totalEstimate = rssEstimate !== null ? rssEstimate + selectedBaseCorpus.length : null;

  const selectStyle = {
    padding: '4px 8px', borderRadius: 4, border: '1px solid var(--doc-border)',
    background: 'var(--doc-surface)', color: 'var(--doc-text)',
    fontFamily: 'var(--mono)', fontSize: 12, cursor: 'pointer',
  };

  return createPortal(
    <div className="rp-modal-backdrop" onClick={!submitting ? onClose : undefined}>
      <div
        className="rp-modal"
        style={{ width: 680, maxWidth: '95vw' }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="mh">
          <div>
            <h3>Initial Load / Corpus Reload</h3>
            <div style={{ fontSize: 12, color: 'var(--doc-text-2)', marginTop: 3, maxWidth: 520 }}>
              Select document categories and date range. This operation will wipe and re-ingest the selected corpus.
            </div>
          </div>
          <button className={`close ${submitting ? 'disabled' : ''}`} onClick={!submitting ? onClose : undefined}>
            <CloseIcon />
          </button>
        </div>

        {/* ── Body ── */}
        <div className="mbody">
          {loading && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 12 }}>
              Loading corpus status…
            </div>
          )}

          {loadError && (
            <div style={{ padding: '16px', background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)', fontSize: 13 }}>
              {loadError}
            </div>
          )}

          {!loading && !loadError && bootstrapStatus && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

              {/* ── Section 1: Base Corpus ── */}
              <section>
                <SectionLabel badge={`${selectedBaseCorpus.length} / ${bootstrapStatus.base_corpus.length}`}>
                  Base Corpus
                </SectionLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {bootstrapStatus.base_corpus.map(doc => {
                    const checked = selectedBaseCorpus.includes(doc.document_id);
                    return (
                      <div
                        key={doc.document_id}
                        className="rp-check-row"
                        onClick={() => setSelectedBaseCorpus(prev =>
                          checked ? prev.filter(id => id !== doc.document_id) : [...prev, doc.document_id]
                        )}
                      >
                        <span className={`rp-check ${checked ? 'on' : ''}`}>
                          {checked && <CheckIcon />}
                        </span>
                        <StatusDot status={doc.ingestion_status} />
                        <span className="cls" style={{ flex: 1 }}>{doc.document_title}</span>
                        <AgencyBadge agency={doc.issuing_body} />
                        <span className="cnt" style={{ width: 62, textAlign: 'right', flexShrink: 0 }}>
                          {doc.chunk_count > 0 ? `${doc.chunk_count} chunks` : '—'}
                        </span>
                        <span className="cnt" style={{ width: 72, textAlign: 'right', flexShrink: 0 }}>
                          {doc.last_indexed_at ? formatDate(doc.last_indexed_at) : '—'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </section>

              {/* ── Section 2: RSS History ── */}
              <section>
                <SectionLabel badge={`${selectedFeeds.length} / ${bootstrapStatus.rss_feeds.length}`}>
                  RSS History
                </SectionLabel>

                {['FDA', 'EMA', 'ICH'].map(agency => {
                  const feeds = bootstrapStatus.rss_feeds.filter(f => f.agency === agency);
                  if (feeds.length === 0) return null;
                  return (
                    <div key={agency} className="rp-scope-group">
                      <div className="grp-name">{agency}</div>
                      {feeds.map(feed => {
                        const checked = selectedFeeds.includes(feed.feed_id);
                        return (
                          <div
                            key={feed.feed_id}
                            className="rp-check-row"
                            onClick={() => setSelectedFeeds(prev =>
                              checked ? prev.filter(id => id !== feed.feed_id) : [...prev, feed.feed_id]
                            )}
                          >
                            <span className={`rp-check ${checked ? 'on' : ''}`}>
                              {checked && <CheckIcon />}
                            </span>
                            <span className="cls">{feed.label}</span>
                            <span className="cnt" style={{ fontStyle: 'italic', marginRight: 6 }}>{feed.description}</span>
                            <span className="cnt">
                              {feed.doc_count.toLocaleString()} docs
                              {feed.date_min && feed.date_max && (
                                <> · {feed.date_min.slice(0, 4)}–{feed.date_max.slice(0, 4)}</>
                              )}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}

                {/* Historical depth control */}
                {selectedFeeds.length > 0 && (
                  <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--doc-border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 8 }}>Historical depth</div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {DATE_WINDOW_OPTIONS.map(opt => {
                        const active = dateWindow === opt.value;
                        return (
                          <button
                            key={opt.value}
                            onClick={() => setDateWindow(opt.value)}
                            style={{
                              padding: '5px 12px', borderRadius: 4, fontSize: 12,
                              fontFamily: 'var(--mono)', cursor: 'pointer',
                              background: active ? 'var(--accent-l, #2563eb)' : 'transparent',
                              color: active ? '#fff' : 'var(--doc-text-2)',
                              border: `1px solid ${active ? 'var(--accent-l, #2563eb)' : 'var(--doc-border)'}`,
                              transition: 'all 100ms ease',
                            }}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>

                    {/* All available warning */}
                    {dateWindow === 'all' && (
                      <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'flex-start', padding: '8px 10px', background: 'var(--warn-tint)', border: '1px solid var(--warn-tint-border)', borderRadius: 4 }}>
                        <WarnIcon />
                        <span style={{ fontSize: 12, color: 'var(--warn-text)', lineHeight: 1.5 }}>
                          Fetching all available history may take 30–60 minutes.
                          {rssEstimate != null && rssEstimate > 0 && (
                            <> Estimated <b>{rssEstimate.toLocaleString()}</b> documents.</>
                          )}
                        </span>
                      </div>
                    )}

                    {/* Custom year dropdowns */}
                    {dateWindow === 'custom' && (
                      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
                        <span style={{ color: 'var(--doc-text-2)', fontSize: 12 }}>From</span>
                        <select value={customFromYear} onChange={e => setCustomFromYear(parseInt(e.target.value))} style={selectStyle}>
                          {yearOptions.map(y => <option key={y} value={y}>{y}</option>)}
                        </select>
                        <span style={{ color: 'var(--doc-text-2)', fontSize: 12 }}>to</span>
                        <select value={customToYear} onChange={e => setCustomToYear(parseInt(e.target.value))} style={selectStyle}>
                          {yearOptions.filter(y => y >= customFromYear).map(y => <option key={y} value={y}>{y}</option>)}
                        </select>
                      </div>
                    )}

                    {/* Live estimate */}
                    <div style={{ marginTop: 8, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>
                      {estimate == null
                        ? 'Calculating estimate…'
                        : estimate.estimated_docs == null
                          ? `Estimate unavailable — ${estimate.note}`
                          : `~${estimate.estimated_docs.toLocaleString()} RSS documents in this date range`
                      }
                    </div>
                  </div>
                )}
              </section>

              {/* ── Section 3: Source files ── */}
              <section>
                <SectionLabel>Source files</SectionLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {[
                    { value: 'changed_only',   label: 'Re-download if changed',  hint: 'Compare hash; fetch only when source differs' },
                    { value: 'full_redownload', label: 'Re-download everything',  hint: 'Delete and re-fetch all files from original sources' },
                  ].map(opt => {
                    const active = sourceMode === opt.value;
                    return (
                      <label
                        key={opt.value}
                        onClick={() => setSourceMode(opt.value)}
                        style={{
                          display: 'flex', alignItems: 'flex-start', gap: 10,
                          padding: '8px 10px', borderRadius: 4, cursor: 'pointer',
                          background: active ? 'rgba(96,165,250,0.10)' : 'transparent',
                          border: '1px solid var(--doc-border)',
                          borderLeft: active ? '3px solid var(--accent-l, #60a5fa)' : '1px solid var(--doc-border)',
                          transition: 'all 120ms ease',
                        }}
                      >
                        <span style={{
                          width: 14, height: 14, borderRadius: 7, flexShrink: 0, marginTop: 1,
                          border: `2px solid ${active ? 'var(--accent-l, #60a5fa)' : 'var(--doc-border)'}`,
                          background: 'transparent',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          {active && <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--accent-l, #60a5fa)' }} />}
                        </span>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, color: 'var(--doc-text)', fontWeight: active ? 500 : 400 }}>{opt.label}</div>
                          <div style={{ fontSize: 11, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', marginTop: 2 }}>{opt.hint}</div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </section>

              {/* ── Section 4: Confirmation ── */}
              <div style={{ borderTop: '1px solid var(--doc-border)', paddingTop: 16 }}>
                <label className="rp-wipe-check" onClick={() => setConfirmed(c => !c)}>
                  <span className={`rp-check warn ${confirmed ? 'on' : ''}`}>
                    {confirmed && <CheckIcon />}
                  </span>
                  <span className="ctxt">I understand this will wipe and re-ingest the selected corpus</span>
                </label>
              </div>

            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="mfoot" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)' }}>
            {!loading && totalEstimate !== null
              ? `~${totalEstimate.toLocaleString()} documents selected`
              : !loading && selectedBaseCorpus.length > 0
                ? `${selectedBaseCorpus.length} base corpus doc${selectedBaseCorpus.length !== 1 ? 's' : ''} + RSS feeds`
                : ''
            }
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {submitError && (
              <span style={{ fontSize: 12, color: 'var(--err-text)', maxWidth: 260 }}>{submitError}</span>
            )}
            <button className="rp-mbtn ghost" onClick={!submitting ? onClose : undefined} disabled={submitting}>
              Cancel
            </button>
            <button
              className={`rp-mbtn primary ${!canSubmit ? 'disabled' : ''}`}
              onClick={canSubmit ? handleSubmit : undefined}
              disabled={!canSubmit}
              style={canSubmit ? { background: 'var(--status-error, #ef4444)', borderColor: 'var(--status-error, #ef4444)' } : {}}
            >
              {submitting ? 'Starting…' : 'Start Initial Load'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
