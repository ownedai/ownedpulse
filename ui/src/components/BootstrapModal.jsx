import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { formatDate } from '../dateFormat';
import { getBootstrapStatus, getBootstrapState, getDateEstimate, postSourcesBootstrap } from '../api/client';
import { useBootstrapProgress } from '../hooks/useBootstrapProgress';

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
  if (dateWindow === '30days') {
    const d = new Date(); d.setDate(d.getDate() - 30);
    return { date_from: d.toISOString().slice(0, 10), date_to: null };
  }
  const thisYear = new Date().getFullYear();
  if (dateWindow === '1year')  return { date_from: `${thisYear - 1}-01-01`, date_to: null };
  if (dateWindow === '3years') return { date_from: `${thisYear - 3}-01-01`, date_to: null };
  if (dateWindow === '5years') return { date_from: `${thisYear - 5}-01-01`, date_to: null };
  if (dateWindow === 'all')    return { date_from: null, date_to: null };
  if (dateWindow === 'custom') return { date_from: `${customFromYear}-01-01`, date_to: `${customToYear}-12-31` };
  return { date_from: null, date_to: null };
}

// ── Main component ────────────────────────────────────────────────────────────

export default function BootstrapModal({ onClose, onStarted, autoSubmit = false, enabledSources = null }) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [bootstrapStatus, setBootstrapStatus] = useState(null);

  const defaultSources = enabledSources
    ? Object.fromEntries(enabledSources.map(id => [id, true]))
    : { fda_press_releases: true, ema_reg_guidance: true, ema_sci_guidelines: true, ich_guidelines: true };
  const [includeBaseCorpus, setIncludeBaseCorpus] = useState(!autoSubmit);
  const [selectedSources, setSelectedSources]     = useState(defaultSources);
  const [depth, setDepth]                         = useState(autoSubmit ? '30days' : '1year');
  const [customFromYear, setCustomFromYear]       = useState(new Date().getFullYear() - 5);
  const [customToYear, setCustomToYear]           = useState(new Date().getFullYear());
  const [fileStrategy, setFileStrategy]           = useState('use_local');
  const [confirmed, setConfirmed]                 = useState(false);
  const [nuclearConfirmed, setNuclearConfirmed]   = useState(false);
  const [estimate, setEstimate]                   = useState(null);
  const [submitting, setSubmitting]               = useState(false);
  const [submitError, setSubmitError]             = useState(null);

  // Running / complete state — persisted across modal close via shared hook
  const {
    uiMode, sessionId, progress, stopping, docEvents,
    start: startTracking, stop: stopTracking, dismiss,
  } = useBootstrapProgress();
  const [localUiMode, setLocalUiMode] = useState('config'); // modal-specific: 'config' | 'running' | 'complete'
  const connectionLost = progress.status === 'disconnected' || progress.status === 'session_lost';

  const estimateAbortRef   = useRef(null);
  const estimateTimeoutRef = useRef(null);
  const autoSubmittedRef   = useRef(false);

  // Sync modal UI state with the shared tracking state
  useEffect(() => {
    if (uiMode === 'running' && localUiMode !== 'running') {
      setLocalUiMode('running');
    } else if (uiMode === 'complete' && localUiMode === 'running') {
      setLocalUiMode('complete');
    } else if (uiMode === 'idle') {
      setLocalUiMode('config');
    }
  }, [uiMode, localUiMode]);

  // Load bootstrap status on mount; auto-reconnect to any active session
  useEffect(() => {
    let cancelled = false;
    getBootstrapStatus()
      .then(data => {
        if (cancelled) return;
        setBootstrapStatus(data);
        // Auto-submit: fire immediately once data is loaded
        if (autoSubmit && !autoSubmittedRef.current) {
          autoSubmittedRef.current = true;
          handleSubmit();
        }
      })
      .catch(err => { if (!cancelled) setLoadError(err.message || 'Failed to load corpus status'); })
      .finally(() => { if (!cancelled) setLoading(false); });

    // Check for an active session and reconnect to it
    getBootstrapState()
      .then(state => {
        if (state.active_session) {
          setLocalUiMode('running');
          startTracking(state.active_session);
          setLocalUiMode('running');
        }
      })
      .catch(() => {});
  }, [startTracking]);

  // Sync selectedSources from enabledSources prop (arrives after first render)
  useEffect(() => {
    if (enabledSources && enabledSources.length > 0) {
      setSelectedSources(Object.fromEntries(enabledSources.map(id => [id, true])));
    }
  }, [enabledSources]);

  // Poll registry-status while discovery is running at startup
  const [registryStatus, setRegistryStatus] = useState(null);
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch('/api/system/registry-status');
        const data = await res.json();
        if (!active) return;
        setRegistryStatus(data);
        if (data.discovery_running) {
          setTimeout(poll, 5000);
        }
      } catch (_) {
        // Non-critical — modal still works without live status
      }
    };
    poll();
    return () => { active = false; };
  }, []);

  // Refresh estimate whenever selection or date window changes
  const activeSources = Object.entries(selectedSources).filter(([,v]) => v).map(([k]) => k);
  const sourceCount = activeSources.length + (includeBaseCorpus ? 1 : 0);

  const refreshEstimate = useCallback(() => {
    if (estimateTimeoutRef.current) clearTimeout(estimateTimeoutRef.current);
    estimateTimeoutRef.current = setTimeout(() => {
      if (estimateAbortRef.current) estimateAbortRef.current.abort();
      if (activeSources.length === 0) {
        setEstimate({ estimated_docs: 0, estimated_chunks: 0, note: '' });
        return;
      }
      const ctrl = new AbortController();
      estimateAbortRef.current = ctrl;
      const { date_from, date_to } = getDateRange(depth, customFromYear, customToYear);
      getDateEstimate(activeSources, date_from, date_to, ctrl.signal)
        .then(data => { if (!ctrl.signal.aborted) setEstimate(data); })
        .catch(() => {});
    }, 300);
  }, [activeSources, depth, customFromYear, customToYear]);

  useEffect(() => {
    if (!loading) refreshEstimate();
  }, [activeSources, depth, customFromYear, customToYear, loading, refreshEstimate]);

  // Notify other pages when bootstrap completes (e.g. CorpusPage auto-refresh)
  useEffect(() => {
    if (uiMode === 'complete') {
      window.dispatchEvent(new CustomEvent('regpulse:bootstrap-complete'));
    }
  }, [uiMode]);
  useEffect(() => () => {
    if (estimateTimeoutRef.current) clearTimeout(estimateTimeoutRef.current);
    if (estimateAbortRef.current) estimateAbortRef.current.abort();
  }, []);

  async function handleSubmit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const { date_from, date_to } = getDateRange(depth, customFromYear, customToYear);
      const mode = fileStrategy === 'nuclear' ? 'full_reset' : 'wipe_and_reload';
      const redownload = fileStrategy === 'use_local' ? 'none' : 'force';
      const baseCorpusIds = includeBaseCorpus ? (bootstrapStatus?.base_corpus || []).map(d => d.document_id) : [];
      const payload = {
        mode,
        redownload,
        base_corpus: baseCorpusIds,
        rss_feeds: activeSources.map(feed_id => ({ feed_id, date_from, date_to })),
      };
      const result = await postSourcesBootstrap(payload);

      setSubmitting(false);
      startTracking(result.session_id);
      setLocalUiMode('running');
      onStarted?.(result);
    } catch (err) {
      setSubmitError(err.message || 'Failed to start bootstrap');
      setSubmitting(false);
    }
  }

  async function handleStop() {
    if (!sessionId || stopping) return;
    stopTracking();
    setLocalUiMode('complete');
  }

  const ingestionRunning = uiMode === 'running';

  const feedDateMin = bootstrapStatus?.sources
    ?.filter(f => f.date_min)
    ?.reduce((min, f) => (!min || f.date_min < min ? f.date_min : min), null);
  const minYear = feedDateMin ? parseInt(feedDateMin.slice(0, 4)) : new Date().getFullYear() - 30;
  const maxYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: maxYear - minYear + 1 }, (_, i) => minYear + i);

  const selectStyle = {
    padding: '4px 8px', borderRadius: 4, border: '1px solid var(--doc-border)',
    background: 'var(--doc-surface)', color: 'var(--doc-text)',
    fontFamily: 'var(--mono)', fontSize: 12, cursor: 'pointer',
  };
  const hasSelection = includeBaseCorpus || activeSources.length > 0;
  const canSubmit = confirmed && !submitting && !loading && !ingestionRunning && hasSelection && (fileStrategy !== 'nuclear' || nuclearConfirmed);
  const rssEstimate = estimate?.estimated_docs ?? null;
  const baseCount = includeBaseCorpus ? (bootstrapStatus?.base_corpus?.length || 9) : 0;
  const totalEstimate = rssEstimate !== null ? rssEstimate + baseCount : (hasSelection ? baseCount + 30 : null);

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
          {!autoSubmit && loading && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 12 }}>
              Loading corpus status…
            </div>
          )}

          {loadError && (
            <div style={{ padding: '16px', background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)', fontSize: 13 }}>
              {loadError}
            </div>
          )}

          {autoSubmit && localUiMode === 'config' && !submitError && (
            <div style={{ textAlign: 'center', padding: '60px 0' }}>
              <div style={{ width: 32, height: 32, borderRadius: 16, border: '3px solid var(--doc-border)', borderTopColor: 'var(--accent-l)', animation: 'spin 0.8s linear infinite', margin: '0 auto' }} />
              <div style={{ marginTop: 16, fontSize: 13, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)' }}>
                Starting ingestion…
              </div>
            </div>
          )}

          {autoSubmit && submitError && (
            <div style={{ padding: '16px', background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)', fontSize: 13 }}>
              {submitError}
            </div>
          )}

          {/* ── Running / complete view ── */}
          {(uiMode === 'running' || uiMode === 'complete') && (() => {
            const pct = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
            const wasStopped = stopping && uiMode === 'complete';
            const wasDisconnected = connectionLost && !wasStopped;
            const isFinished = !wasDisconnected && uiMode === 'complete';
            const allFailed = isFinished && progress.failed > 0 && progress.succeeded === 0;
            const partial   = isFinished && progress.failed > 0 && progress.succeeded > 0;
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* Status badge + session id + stop button */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {uiMode === 'running' && !connectionLost ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, fontFamily: 'var(--mono)', letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 600, padding: '2px 8px', borderRadius: 2, background: 'var(--info-tint, #eff6ff)', color: 'var(--accent-l)', border: '1px solid var(--info-tint-border, #bfdbfe)', animation: 'pulse 1.5s ease-in-out infinite' }}>
                      {stopping ? 'Stopping…' : 'Running'}
                    </span>
                  ) : connectionLost ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, fontFamily: 'var(--mono)', letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 600, padding: '2px 8px', borderRadius: 2, background: 'var(--warn-tint)', color: 'var(--warn-text)', border: '1px solid var(--warn-tint-border)' }}>
                      {uiMode === 'running' ? 'Reconnecting…' : 'Connection lost'}
                    </span>
                  ) : (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, fontFamily: 'var(--mono)', letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 600, padding: '2px 8px', borderRadius: 2, background: wasStopped ? 'var(--warn-tint)' : allFailed ? 'var(--err-tint)' : partial ? 'var(--warn-tint)' : 'var(--ok-tint)', color: wasStopped ? 'var(--warn-text)' : allFailed ? 'var(--err-text)' : partial ? 'var(--warn-text)' : 'var(--ok-text)', border: `1px solid ${wasStopped ? 'var(--warn-tint-border)' : allFailed ? 'var(--err-tint-border)' : partial ? 'var(--warn-tint-border)' : 'var(--ok-tint-border)'}` }}>
                      {wasStopped ? 'Stopped' : allFailed ? 'Failed' : partial ? 'Completed with errors' : 'Complete'}
                    </span>
                  )}
                  {sessionId && (
                    <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>
                      session {sessionId.slice(0, 8)}…
                    </span>
                  )}
                  {uiMode === 'running' && !stopping && (
                    <button
                      onClick={handleStop}
                      style={{ marginLeft: 'auto', padding: '3px 10px', borderRadius: 4, border: '1px solid var(--err-text, #ef4444)', fontSize: 11, fontFamily: 'var(--mono)', cursor: 'pointer', background: 'transparent', color: 'var(--err-text, #ef4444)', transition: 'all 120ms ease' }}
                    >
                      Stop
                    </button>
                  )}
                </div>

                {/* Progress bar */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span style={{ fontSize: 13, color: 'var(--doc-text)' }}>
                      Processing <b>{progress.processed}</b> / {progress.total}
                    </span>
                    <span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--doc-text-2)' }}>
                      {pct}%
                      {uiMode === 'running' && progress.eta_seconds > 0 && (
                        <> &middot; {progress.eta_seconds < 60 ? '<1m' : progress.eta_seconds < 3600 ? `~${Math.round(progress.eta_seconds / 60)}m` : `~${(progress.eta_seconds / 3600).toFixed(1)}h`} left</>
                      )}
                    </span>
                  </div>
                  <div style={{ height: 6, borderRadius: 3, background: 'var(--doc-bg)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', borderRadius: 3, background: allFailed ? 'var(--err-text)' : partial ? 'var(--warn-text)' : 'var(--accent-l)', width: `${pct}%`, transition: 'width 400ms ease' }} />
                  </div>
                  <div style={{ display: 'flex', gap: 16, fontSize: 12, fontFamily: 'var(--mono)' }}>
                    <span style={{ color: 'var(--ok-text)' }}>Succeeded <b>{progress.succeeded}</b></span>
                    <span style={{ color: progress.skipped > 0 ? 'var(--warn, #f59e0b)' : 'var(--doc-text-3)' }}>Skipped <b>{progress.skipped}</b></span>
                    <span style={{ color: progress.failed > 0 ? 'var(--err-text)' : 'var(--doc-text-3)' }}>Failed <b>{progress.failed}</b></span>
                  </div>
                </div>

                {/* Per-doc event stream */}
                {docEvents.length > 0 && (
                  <div style={{ maxHeight: 220, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2, borderRadius: 4, border: '1px solid var(--doc-border)', padding: '6px 8px', background: 'var(--doc-bg)' }}>
                    {docEvents.map((d, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '3px 0' }}>
                        <span style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600, padding: '1px 5px', borderRadius: 2, flexShrink: 0, marginTop: 1,
                          background: d.status === 'ok' ? 'var(--ok-tint)' : d.status === 'skipped' ? 'var(--warn-tint, rgba(245,158,11,0.1))' : 'var(--err-tint)',
                          color: d.status === 'ok' ? 'var(--ok-text)' : d.status === 'skipped' ? 'var(--warn, #f59e0b)' : 'var(--err-text)',
                          border: `1px solid ${d.status === 'ok' ? 'var(--ok-tint-border)' : d.status === 'skipped' ? 'rgba(245,158,11,0.3)' : 'var(--err-tint-border)'}` }}>
                          {d.status === 'ok' ? 'OK' : d.status === 'skipped' ? 'SKIP' : 'ERR'}
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--doc-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.doc_id}</div>
                          {d.status === 'ok' && d.chunks != null && (
                            <div style={{ fontSize: 11, color: 'var(--doc-text-3)', fontFamily: 'var(--mono)' }}>{d.chunks} chunks</div>
                          )}
                          {d.status === 'skipped' && d.reason && (
                            <div style={{ fontSize: 11, color: 'var(--warn, #f59e0b)', fontFamily: 'var(--mono)' }}>{d.reason}</div>
                          )}
                          {d.status === 'failed' && d.reason && (
                            <div style={{ fontSize: 11, color: 'var(--err-text)', fontFamily: 'var(--mono)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{d.reason}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {uiMode === 'running' && connectionLost && (
                  <div style={{ padding: '10px 12px', borderRadius: 4, fontSize: 12.5, background: 'var(--warn-tint)', color: 'var(--warn-text)', border: '1px solid var(--warn-tint-border)' }}>
                    Connection to the server was lost — reconnecting. The background job is still running.
                  </div>
                )}

                {uiMode === 'complete' && (
                  <div style={{ padding: '10px 12px', borderRadius: 4, fontSize: 12.5, background: wasDisconnected ? 'var(--warn-tint)' : wasStopped ? 'var(--warn-tint)' : allFailed ? 'var(--err-tint)' : partial ? 'var(--warn-tint)' : 'var(--ok-tint)', color: wasDisconnected ? 'var(--warn-text)' : wasStopped ? 'var(--warn-text)' : allFailed ? 'var(--err-text)' : partial ? 'var(--warn-text)' : 'var(--ok-text)', border: `1px solid ${wasDisconnected ? 'var(--warn-tint-border)' : wasStopped ? 'var(--warn-tint-border)' : allFailed ? 'var(--err-tint-border)' : partial ? 'var(--warn-tint-border)' : 'var(--ok-tint-border)'}` }}>
                    {wasDisconnected
                      ? `Connection to the server was lost — the background job may still be running. Check Run Log for final status.`
                      : wasStopped
                      ? `Stopped after ${progress.processed} / ${progress.total} documents — ${progress.succeeded} succeeded · ${progress.failed} failed${progress.skipped > 0 ? ` · ${progress.skipped} skipped` : ''}`
                      : `${progress.succeeded} succeeded · ${progress.failed} failed${progress.skipped > 0 ? ` · ${progress.skipped} skipped` : ''}`
                    }
                    {!wasDisconnected && (allFailed || partial) && ' — check Run Log for details'}
                  </div>
                )}
              </div>
            );
          })()}

          {!autoSubmit && !loading && !loadError && bootstrapStatus && localUiMode === 'config' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

              {/* ── Section 1: Base Corpus ── */}
              <section>
                <SectionLabel>Base Corpus</SectionLabel>
                <div
                  className="rp-check-row"
                  onClick={() => setIncludeBaseCorpus(p => !p)}
                >
                  <span className={`rp-check ${includeBaseCorpus ? 'on' : ''}`}>
                    {includeBaseCorpus && <CheckIcon />}
                  </span>
                  <span className="cls" style={{ flex: 1 }}>
                    Include base corpus ({bootstrapStatus.base_corpus.length} curated regulatory documents)
                  </span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--doc-text-3)', fontFamily: 'var(--mono)', marginTop: 4, marginLeft: 26 }}>
                  Annex 11, 21 CFR Part 11, ICH Q10, EU GMP Annex 15 & 22 — always fast
                </div>
              </section>

              {/* ── Section 2: Sources ── */}
              <section>
                <SectionLabel>Sources</SectionLabel>
                {['FDA', 'EMA', 'ICH'].map(agency => {
                  const feeds = (bootstrapStatus.sources || []).filter(f => f.agency === agency);
                  if (feeds.length === 0) return null;
                  return (
                    <div key={agency} className="rp-scope-group">
                      <div className="grp-name">{agency}</div>
                      {feeds.map(feed => {
                        const checked = selectedSources[feed.feed_id] !== false;
                        return (
                          <div
                            key={feed.feed_id}
                            className="rp-check-row"
                            onClick={() => setSelectedSources(prev => ({ ...prev, [feed.feed_id]: !prev[feed.feed_id] }))}
                          >
                            <span className={`rp-check ${checked ? 'on' : ''}`}>
                              {checked && <CheckIcon />}
                            </span>
                            <span className="cls">{feed.label}</span>
                            <span className="cnt" style={{ fontStyle: 'italic', marginRight: 6 }}>{feed.description}</span>
                            <span className="cnt">
                              {(() => {
                                const count = feed.doc_count;
                                if (count > 0) return `${count.toLocaleString()} docs`;
                                return '— docs';
                              })()}
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
              </section>

              {/* ── Section 3: Historical Depth ── */}
              <section>
                <SectionLabel>Historical Depth</SectionLabel>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {DATE_WINDOW_OPTIONS.map(opt => {
                    const active = depth === opt.value;
                    return (
                      <button
                        key={opt.value}
                        onClick={() => setDepth(opt.value)}
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
                {depth === 'custom' && (
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
                <div style={{ marginTop: 8, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>
                  {estimate == null
                    ? 'Calculating estimate…'
                    : estimate.estimated_docs == null
                      ? `Estimate unavailable — ${estimate.note}`
                      : `~${estimate.estimated_docs.toLocaleString()} documents in this date range`
                  }
                </div>
              </section>

              {/* ── Section 4: File Strategy ── */}
              <section>
                <SectionLabel>File Strategy</SectionLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {[
                    { value: 'use_local',   label: 'Use local files where available', hint: 'Re-chunk and re-embed without re-downloading — fastest option' },
                    { value: 'redownload',  label: 'Re-download selected sources',    hint: 'Re-fetch files even if local copies exist' },
                    { value: 'nuclear',     label: '☢ Nuclear reset',                  hint: 'Wipes ALL cached files including unselected sources, then re-downloads selected. Cannot be undone.' },
                  ].map(opt => {
                    const active = fileStrategy === opt.value;
                    const isNuclear = opt.value === 'nuclear';
                    return (
                      <label
                        key={opt.value}
                        onClick={() => setFileStrategy(opt.value)}
                        style={{
                          display: 'flex', alignItems: 'flex-start', gap: 10,
                          padding: '8px 10px', borderRadius: 4, cursor: 'pointer',
                          background: active ? (isNuclear ? 'rgba(245,158,11,0.10)' : 'rgba(96,165,250,0.10)') : 'transparent',
                          border: '1px solid var(--doc-border)',
                          borderLeft: active ? `3px solid ${isNuclear ? 'var(--warn, #f59e0b)' : 'var(--accent-l, #60a5fa)'}` : '1px solid var(--doc-border)',
                          transition: 'all 120ms ease',
                        }}
                      >
                        <span style={{
                          width: 14, height: 14, borderRadius: 7, flexShrink: 0, marginTop: 1,
                          border: `2px solid ${active ? (isNuclear ? 'var(--warn, #f59e0b)' : 'var(--accent-l, #60a5fa)') : 'var(--doc-border)'}`,
                          background: 'transparent',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          {active && <span style={{ width: 6, height: 6, borderRadius: 3, background: isNuclear ? 'var(--warn, #f59e0b)' : 'var(--accent-l, #60a5fa)' }} />}
                        </span>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, color: active && isNuclear ? 'var(--warn-text)' : 'var(--doc-text)', fontWeight: active ? 500 : 400 }}>{opt.label}</div>
                          <div style={{ fontSize: 11, color: active && isNuclear ? 'var(--warn-text)' : 'var(--doc-text-2)', fontFamily: 'var(--mono)', marginTop: 2 }}>{opt.hint}</div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </section>

              {/* ── Section 5: Confirmation ── */}
              <div style={{ borderTop: '1px solid var(--doc-border)', paddingTop: 16 }}>
                <label className="rp-wipe-check" onClick={() => setConfirmed(c => !c)}>
                  <span className={`rp-check warn ${confirmed ? 'on' : ''}`}>
                    {confirmed && <CheckIcon />}
                  </span>
                  <span className="ctxt">I understand this will wipe and re-ingest the selected corpus</span>
                </label>
                {fileStrategy === 'nuclear' && (
                  <label className="rp-wipe-check" onClick={() => setNuclearConfirmed(c => !c)} style={{ marginTop: 8 }}>
                    <span className={`rp-check warn ${nuclearConfirmed ? 'on' : ''}`} style={{ borderColor: 'var(--warn, #f59e0b)' }}>
                      {nuclearConfirmed && <CheckIcon />}
                    </span>
                    <span className="ctxt" style={{ color: 'var(--warn-text)' }}>I understand Nuclear will delete ALL cached files</span>
                  </label>
                )}
              </div>

            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="mfoot" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)' }}>
            {!autoSubmit && localUiMode === 'config' && !loading
              ? `~${totalEstimate.toLocaleString()} documents selected`
              : localUiMode === 'running'
                ? 'You can close this window — progress is shown in the status bar'
                : ''
            }
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {!autoSubmit && ingestionRunning && localUiMode === 'config' && (
              <span style={{ fontSize: 12, color: '#f59e0b', fontFamily: 'var(--mono)', fontWeight: 600 }}>
                Ingestion already running — wait for it to finish
              </span>
            )}
            {!autoSubmit && submitError && localUiMode === 'config' && (
              <span style={{ fontSize: 12, color: 'var(--err-text)', maxWidth: 260 }}>{submitError}</span>
            )}
            {!autoSubmit && localUiMode === 'config' && (
              <>
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
              </>
            )}
            {uiMode === 'running' && (
              <button className="rp-mbtn ghost disabled" disabled>
                Running…
              </button>
            )}
            {uiMode === 'complete' && (
              <button className="rp-mbtn primary" onClick={onClose}>
                Close
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
