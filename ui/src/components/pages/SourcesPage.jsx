import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import {
  getCorpusSummary, getBootstrapState,
  startBootstrapRun, activateRss,
  getAdminFeeds, toggleFeed, triggerFeedRun,
  getSchedulerStatus, pauseScheduler, resumeScheduler,
  getSchedulerConfig, updateSchedulerConfig,
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

function groupByFamily(docs) {
  // Separate docs with and without family_id
  const byFamily = {};
  const standalone = [];

  for (const doc of docs) {
    if (doc.document_family_id) {
      if (!byFamily[doc.document_family_id]) byFamily[doc.document_family_id] = [];
      byFamily[doc.document_family_id].push(doc);
    } else {
      standalone.push(doc);
    }
  }

  // Within each family, sort by publication_date desc (newest = current version)
  const familyGroups = Object.values(byFamily).map((group) => {
    const sorted = [...group].sort((a, b) => (b.publication_date || '') > (a.publication_date || '') ? 1 : -1);
    return { current: sorted[0], superseded: sorted.slice(1) };
  });

  // Build flat rows for rendering: standalones interleaved, families as groups
  const result = [];
  for (const doc of standalone) {
    result.push({ type: 'doc', doc, superseded: [] });
  }
  for (const g of familyGroups) {
    result.push({ type: 'doc', doc: g.current, superseded: g.superseded });
  }
  // Sort: by publication_date desc within each top-level entry
  result.sort((a, b) => (b.doc.publication_date || '') > (a.doc.publication_date || '') ? 1 : -1);
  return result;
}

function BaseCorpusCard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});
  const [reingesting, setReingesting] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    getCorpusDocumentsV2({ page: 1, page_size: 50, corpus_doc: true })
      .then((d) => setItems(d.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  function toggleExpand(docId) {
    setExpanded((prev) => ({ ...prev, [docId]: !prev[docId] }));
  }

  async function handleReingest(docId) {
    setReingesting(docId);
    try { await reingestDoc(docId); } catch (_) {}
    setTimeout(() => { setReingesting(null); load(); }, 3000);
  }

  const rows = groupByFamily(items);

  return (
    <div className="rp-src-card">
      <div className="rp-src-card-lbl">
        <span>Base Corpus</span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--doc-text-3)', fontWeight: 400, marginLeft: 6 }}>
          {items.length > 0 ? `${items.length} curated documents` : ''}
        </span>
        <Link to="/corpus" style={{ marginLeft: 'auto', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--accent-l)', textDecoration: 'none' }}>
          View all →
        </Link>
      </div>

      <table className="rp-table" style={{ fontSize: 12.5 }}>
        <thead>
          <tr>
            <th>Document</th>
            <th style={{ width: 55 }}>Agency</th>
            <th style={{ width: 90 }}>Version</th>
            <th style={{ width: 95 }}>Published</th>
            <th style={{ width: 90 }}>Status</th>
            <th style={{ width: 55, textAlign: 'right' }}>Chunks</th>
            <th style={{ width: 100 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>Loading…</td></tr>
          )}
          {!loading && rows.length === 0 && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>No base corpus documents found.</td></tr>
          )}
          {rows.map(({ doc, superseded }) => (
            <>
              <tr key={doc.document_id} style={{ cursor: superseded.length > 0 ? 'pointer' : undefined }} onClick={superseded.length > 0 ? () => toggleExpand(doc.document_id) : undefined}>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, overflow: 'hidden' }}>
                    {superseded.length > 0 && (
                      <span style={{ color: 'var(--doc-text-3)', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        <ChevronIcon open={!!expanded[doc.document_id]} />
                      </span>
                    )}
                    <Link
                      to={`/corpus/${encodeURIComponent(doc.document_id)}`}
                      state={{ from: 'sources' }}
                      title={doc.document_title}
                      onClick={(e) => e.stopPropagation()}
                      style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5, color: 'var(--accent-l)', textDecoration: 'none' }}
                    >
                      {doc.document_title || doc.document_id}
                    </Link>
                  </div>
                </td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
                  {doc.issuing_body === 'EU-Commission' ? 'EMA' : doc.issuing_body}
                </td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.document_version || '—'}</td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{formatDate(doc.publication_date)}</td>
                <td><StatusBadge status={doc.ingestion_status} /></td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.chunk_count || '—'}</td>
                <td>
                  <div className="rp-act">
                    {reingesting === doc.document_id ? (
                      <span className="btn busy"><span className="sp" /> Reingesting…</span>
                    ) : (
                      <button className="btn" onClick={(e) => { e.stopPropagation(); handleReingest(doc.document_id); }}>
                        <RefreshIcon /> Reingest
                      </button>
                    )}
                  </div>
                </td>
              </tr>
              {expanded[doc.document_id] && superseded.map((sup) => (
                <tr key={sup.document_id} style={{ background: 'var(--doc-bg)', opacity: 0.72 }}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 18, minWidth: 0, overflow: 'hidden' }}>
                      <span style={{ color: 'var(--doc-text-3)', fontFamily: 'var(--mono)', fontSize: 11, userSelect: 'none', flexShrink: 0 }}>└</span>
                      <Link
                        to={`/corpus/${encodeURIComponent(sup.document_id)}`}
                        state={{ from: 'sources' }}
                        title={sup.document_title}
                        style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5, color: 'var(--doc-text-2)', textDecoration: 'none' }}
                      >
                        {sup.document_title || sup.document_id}
                      </Link>
                    </div>
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
                    {sup.issuing_body === 'EU-Commission' ? 'EMA' : sup.issuing_body}
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>{sup.document_version || '—'}</td>
                  <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>{formatDate(sup.publication_date)}</td>
                  <td>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600,
                      letterSpacing: '0.06em', textTransform: 'uppercase',
                      padding: '2px 7px', borderRadius: 2,
                      background: 'var(--warn-tint)', color: 'var(--warn-text)', border: '1px solid var(--warn-tint-border)',
                    }}>
                      Superseded
                    </span>
                  </td>
                  <td style={{ textAlign: 'right', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>{sup.chunk_count || '—'}</td>
                  <td style={{ color: 'var(--doc-text-3)', fontSize: 11, fontFamily: 'var(--mono)' }}>—</td>
                </tr>
              ))}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChevronIcon({ open }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 150ms', flexShrink: 0 }}>
      <path d="M3 2l4 3-4 3z" />
    </svg>
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

// ── Schedule Modal ────────────────────────────────────────────────────────────

const TIMEZONES = [
  'Europe/Berlin',
  'Europe/London',
  'UTC',
  'US/Eastern',
  'US/Pacific',
  'Asia/Tokyo',
];

function ScheduleModal({ schedStatus, onClose, onSaved }) {
  const [config, setConfig] = useState(null);
  const [hour, setHour] = useState(9);
  const [minute, setMinute] = useState(0);
  const [timezone, setTimezone] = useState('Europe/Berlin');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [pausing, setPausing] = useState(false);

  useEffect(() => {
    getSchedulerConfig()
      .then((c) => {
        setConfig(c);
        setHour(c.hour);
        setMinute(c.minute);
        setTimezone(c.timezone);
      })
      .catch(() => {});
  }, []);

  async function handleSave() {
    setSaving(true);
    setSaveMsg(null);
    try {
      await updateSchedulerConfig(hour, minute, timezone);
      setSaveMsg({ type: 'ok', text: `Schedule saved: daily at ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${timezone}` });
      onSaved();
    } catch (err) {
      setSaveMsg({ type: 'err', text: err.message || 'Failed to save' });
    }
    setSaving(false);
  }

  async function handlePauseResume() {
    setPausing(true);
    try {
      if (schedStatus?.scheduler_running) await pauseScheduler();
      else await resumeScheduler();
      onSaved();
    } catch (_) {}
    setPausing(false);
  }

  const nextRun = schedStatus?.next_run_time
    ? new Date(schedStatus.next_run_time).toLocaleString('en-GB', {
        weekday: 'long', day: '2-digit', month: 'long',
        year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
      })
    : null;

  const inputStyle = {
    padding: '5px 8px', borderRadius: 4, border: '1px solid var(--doc-border)',
    background: 'var(--doc-surface)', color: 'var(--doc-text)',
    fontFamily: 'var(--mono)', fontSize: 13, width: '100%',
  };

  return createPortal(
    <div className="rp-modal-backdrop" onClick={onClose}>
      <div className="rp-modal" style={{ maxWidth: 420 }} onClick={(e) => e.stopPropagation()}>
        <div className="mh">
          <h3>RSS Schedule</h3>
          <button className="close" onClick={onClose}><CloseIcon /></button>
        </div>

        <div className="mbody">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

            {/* Scheduler status */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 4, background: 'var(--doc-bg)', border: '1px solid var(--doc-border)' }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: schedStatus?.scheduler_running ? 'var(--ok)' : 'var(--warn)', flexShrink: 0 }} />
              <div style={{ flex: 1, fontSize: 13 }}>
                <span style={{ color: 'var(--doc-text)' }}>{schedStatus?.scheduler_running ? 'Scheduler running' : 'Scheduler paused'}</span>
                {nextRun && (
                  <span style={{ color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 11, marginLeft: 8 }}>
                    · next: {nextRun}
                  </span>
                )}
                {!nextRun && schedStatus?.scheduler_running && (
                  <span style={{ color: 'var(--doc-text-3)', fontFamily: 'var(--mono)', fontSize: 11, marginLeft: 8 }}>· not scheduled</span>
                )}
              </div>
              <button
                onClick={handlePauseResume}
                disabled={pausing}
                style={{ padding: '3px 10px', borderRadius: 4, border: '1px solid var(--doc-border)', fontSize: 11, fontFamily: 'var(--mono)', cursor: 'pointer', background: 'transparent', color: 'var(--doc-text-2)', whiteSpace: 'nowrap' }}
              >
                {pausing ? '…' : schedStatus?.scheduler_running ? 'Pause' : 'Resume'}
              </button>
            </div>

            {/* Time config */}
            <div>
              <div style={{ fontSize: 10, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--doc-text-3)', fontWeight: 600, marginBottom: 10 }}>
                Scheduled time
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 8, alignItems: 'end' }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 4 }}>Hour (0–23)</div>
                  <input
                    type="number"
                    min={0} max={23}
                    value={hour}
                    onChange={(e) => setHour(Math.max(0, Math.min(23, parseInt(e.target.value, 10) || 0)))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 4 }}>Minute (0–59)</div>
                  <input
                    type="number"
                    min={0} max={59}
                    value={minute}
                    onChange={(e) => setMinute(Math.max(0, Math.min(59, parseInt(e.target.value, 10) || 0)))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 4 }}>Timezone</div>
                  <select
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    style={inputStyle}
                  >
                    {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
                  </select>
                </div>
              </div>
              <div style={{ marginTop: 8, fontSize: 11, color: 'var(--doc-text-3)', fontFamily: 'var(--mono)' }}>
                Will run daily at {String(hour).padStart(2, '0')}:{String(minute).padStart(2, '0')} {timezone}
              </div>
            </div>

            {/* Save feedback */}
            {saveMsg && (
              <div style={{
                padding: '7px 10px', borderRadius: 4, fontSize: 12, fontFamily: 'var(--mono)',
                background: saveMsg.type === 'ok' ? 'var(--ok-tint)' : 'var(--err-tint)',
                color: saveMsg.type === 'ok' ? 'var(--ok-text)' : 'var(--err-text)',
                border: `1px solid ${saveMsg.type === 'ok' ? 'var(--ok-tint-border)' : 'var(--err-tint-border)'}`,
              }}>
                {saveMsg.text}
              </div>
            )}

          </div>
        </div>

        <div className="mfoot">
          <button className="rp-mbtn ghost" onClick={onClose}>Close</button>
          <button
            className="rp-mbtn primary"
            onClick={handleSave}
            disabled={saving || !config}
          >
            {saving ? 'Saving…' : 'Save schedule'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ── RSS Feeds Card ────────────────────────────────────────────────────────────

function RssFeedsCard() {
  const [feeds, setFeeds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(null);
  const [runState, setRunState] = useState(null); // null | 'running' | 'ok' | 'error'
  const [schedStatus, setSchedStatus] = useState(null);
  const [showSchedule, setShowSchedule] = useState(false);

  const fetchData = useCallback(() => {
    setLoading(true);
    Promise.all([
      getAdminFeeds().catch(() => []),
      getSchedulerStatus().catch(() => null),
    ]).then(([f, s]) => {
      setFeeds(f);
      setSchedStatus(s);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const enabledFeeds = feeds.filter((f) => f.enabled);

  async function handleToggle(feedId, current) {
    setToggling(feedId);
    try {
      await toggleFeed(feedId, !current);
      setFeeds((prev) => prev.map((f) => f.feed_id === feedId ? { ...f, enabled: !current } : f));
    } catch (_) {}
    setToggling(null);
  }

  async function handleRunNow() {
    if (runState === 'running' || enabledFeeds.length === 0) return;
    setRunState('running');
    try {
      await Promise.all(enabledFeeds.map((f) => triggerFeedRun(f.feed_id)));
      setRunState('ok');
      setTimeout(() => { setRunState(null); fetchData(); }, 3000);
    } catch (_) {
      setRunState('error');
      setTimeout(() => setRunState(null), 4000);
    }
  }

  function formatNextRun(isoStr) {
    const d = new Date(isoStr);
    return d.toLocaleString('en-GB', {
      weekday: 'short', day: '2-digit', month: 'short',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  const nextRunFormatted = schedStatus?.next_run_time ? formatNextRun(schedStatus.next_run_time) : null;
  const schedLine = schedStatus == null ? null
    : !schedStatus.scheduler_running ? 'Next run not scheduled — scheduler paused'
    : nextRunFormatted ? `Next scheduled run on: ${nextRunFormatted}`
    : 'Next run not scheduled';
  const schedOk = schedStatus?.scheduler_running && !!nextRunFormatted;

  const runBtnLabel = runState === 'running' ? 'Running…'
    : runState === 'ok' ? '✓ Triggered'
    : runState === 'error' ? '✕ Failed'
    : 'Run now';

  return (
    <div className="rp-src-card">
      <div className="rp-src-card-lbl">
        <span>RSS Feeds</span>
        <button
          onClick={fetchData}
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--doc-text-2)', display: 'flex', alignItems: 'center', marginLeft: 6 }}
          title="Refresh"
        >
          <RefreshIcon />
        </button>
        {schedLine && (
          <span style={{ marginLeft: 12, fontSize: 11.5, fontFamily: 'var(--mono)', color: schedOk ? 'var(--doc-text-2)' : 'var(--warn-text)', fontWeight: 400 }}>
            {schedLine}
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={() => setShowSchedule(true)}
            style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--doc-border)', fontSize: 12, fontFamily: 'var(--mono)', cursor: 'pointer', background: 'transparent', color: 'var(--doc-text-2)' }}
          >
            Schedule
          </button>
          <button
            onClick={handleRunNow}
            disabled={runState === 'running' || enabledFeeds.length === 0}
            title="Run all enabled feeds now"
            style={{
              padding: '4px 12px', borderRadius: 4, border: '1px solid',
              fontSize: 12, fontFamily: 'var(--mono)',
              cursor: runState === 'running' ? 'default' : 'pointer',
              borderColor: runState === 'error' ? 'var(--err-text)' : runState === 'ok' ? 'var(--ok-text)' : 'var(--accent-l)',
              background: runState === 'error' ? 'var(--err-tint)' : runState === 'ok' ? 'var(--ok-tint)' : 'transparent',
              color: runState === 'error' ? 'var(--err-text)' : runState === 'ok' ? 'var(--ok-text)' : 'var(--accent-l)',
              transition: 'all 150ms ease',
            }}
          >
            {runBtnLabel}
          </button>
        </div>
      </div>

      <table className="rp-table" style={{ fontSize: 12.5 }}>
        <thead>
          <tr>
            <th>Feed</th>
            <th style={{ width: 65, textAlign: 'center' }}>Enabled</th>
            <th style={{ width: 140 }}>Last Fetch</th>
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr><td colSpan={3} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>Loading…</td></tr>
          )}
          {!loading && feeds.length === 0 && (
            <tr><td colSpan={3} style={{ textAlign: 'center', padding: 24, color: 'var(--doc-text-2)' }}>No feeds configured.</td></tr>
          )}
          {feeds.map((f) => (
            <tr key={f.feed_id} style={{ opacity: f.enabled ? 1 : 0.55 }}>
              <td>
                <div style={{ fontWeight: 500, fontSize: 13 }}>{f.name}</div>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--doc-text-3)', marginTop: 2 }}>
                  {f.feed_id} · {f.feed_type}
                  {f.url && (
                    <span title={f.url} style={{ marginLeft: 4, cursor: 'help' }}>
                      · <span style={{ textDecoration: 'underline dotted' }}>
                        {f.url.length > 40 ? f.url.slice(0, 40) + '…' : f.url}
                      </span>
                    </span>
                  )}
                </div>
              </td>
              <td style={{ textAlign: 'center' }}>
                <button
                  className={`rp-toggle ${f.enabled ? 'on' : ''} ${toggling === f.feed_id ? 'loading' : ''}`}
                  onClick={() => handleToggle(f.feed_id, f.enabled)}
                  disabled={toggling === f.feed_id}
                  title={f.enabled ? 'Disable — excludes from all runs' : 'Enable — includes in scheduled and manual runs'}
                >
                  <span className="thumb" />
                </button>
              </td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
                {f.last_run_at ? formatDateTime(f.last_run_at) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {showSchedule && (
        <ScheduleModal
          schedStatus={schedStatus}
          onClose={() => setShowSchedule(false)}
          onSaved={() => {
            setShowSchedule(false);
            getSchedulerStatus().then(setSchedStatus).catch(() => {});
          }}
        />
      )}
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

const REDOWNLOAD_OPTIONS = [
  { value: 'none',  label: 'Re-ingest from disk',      hint: 'Use already downloaded files — no network access' },
  { value: 'check', label: 'Re-download if changed',   hint: 'Compare hash; fetch only when source differs' },
  { value: 'force', label: 'Re-download everything',   hint: 'Delete and re-fetch all files from original sources' },
];

function InitialLoadModal({ onClose, lastBootstrap, docCount }) {
  const isInitialized = docCount > 0;
  const [mode, setMode] = useState('config'); // config | running | complete
  const [confirmed, setConfirmed] = useState(false);
  const [scope, setScope] = useState({ fda_guidance: true, fda_press: true, ema: true, ich: true });
  const [redownload, setRedownload] = useState('check');
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
      const result = await startBootstrapRun(scope, isInitialized, isInitialized ? redownload : 'none');
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

              {isInitialized && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--doc-text-3)', fontWeight: 600, marginBottom: 10 }}>
                    Source files
                  </div>
                  {REDOWNLOAD_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      onClick={() => setRedownload(opt.value)}
                      style={{
                        display: 'flex', alignItems: 'flex-start', gap: 10,
                        padding: '8px 10px', marginBottom: 4, borderRadius: 4, cursor: 'pointer',
                        background: redownload === opt.value ? 'rgba(96,165,250,0.10)' : 'transparent',
                        border: '1px solid var(--doc-border)',
                        borderLeft: redownload === opt.value ? '3px solid var(--accent-l, #60a5fa)' : '1px solid var(--doc-border)',
                        transition: 'all 120ms ease',
                      }}
                    >
                      <span style={{
                        width: 14, height: 14, borderRadius: 7, flexShrink: 0, marginTop: 1,
                        border: `2px solid ${redownload === opt.value ? 'var(--accent-l, #60a5fa)' : 'var(--doc-border)'}`,
                        background: 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {redownload === opt.value && <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--accent-l, #60a5fa)' }} />}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, color: 'var(--doc-text)', fontWeight: redownload === opt.value ? 500 : 400 }}>{opt.label}</div>
                        <div style={{ fontSize: 11, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', marginTop: 2 }}>{opt.hint}</div>
                      </div>
                    </label>
                  ))}
                </div>
              )}

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
      <div className="rp-src-card-lbl" style={{ marginBottom: 0 }}>
        <span>Initial Load</span>
        <span style={{ marginLeft: 12, fontSize: 11.5, fontFamily: 'var(--mono)', color: 'var(--doc-text-2)', fontWeight: 400 }}>
          {docCount > 0 ? (
            <>
              Corpus last populated: <span style={{ color: 'var(--doc-text)' }}>{lastBootstrap ? formatDateTime(lastBootstrap) : '—'}</span>
              {' · '}
              <span style={{ color: 'var(--doc-text)' }}>{(bootstrapDocCount || 0).toLocaleString()}</span> documents loaded
            </>
          ) : (
            'Corpus is empty — run Initial Load to ingest all regulatory documents.'
          )}
        </span>
        <button
          onClick={onOpenModal}
          style={{ marginLeft: 'auto', padding: '4px 10px', borderRadius: 4, border: '1px solid var(--doc-border)', fontSize: 12, fontFamily: 'var(--mono)', cursor: 'pointer', background: 'transparent', color: 'var(--doc-text-2)', whiteSpace: 'nowrap' }}
        >
          {docCount > 0 ? 'Re-run Initial Load' : 'Run Initial Load'}
        </button>
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
        <RssFeedsCard />
        <BaseCorpusCard />
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
