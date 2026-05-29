import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import Tooltip from '../common/Tooltip';

const AGENCIES = ['All', 'FDA', 'EMA', 'ICH'];
const AGENCY_TIPS = {
  FDA: 'U.S. Food & Drug Administration',
  EMA: 'European Medicines Agency',
  ICH: 'International Council for Harmonisation',
};
const DOC_TYPES = [
  { label: 'All types', value: null },
  { label: 'Guidance', value: 'guidance' },
  { label: 'Press Release', value: 'press-release' },
  { label: 'Reflection Paper', value: 'reflection-paper' },
];
const DATE_PRESETS = [
  { label: 'All time', value: null },
  { label: 'Last 30d', value: '30d' },
  { label: 'Last 90d', value: '90d' },
  { label: 'Custom', value: 'custom' },
];

function useClickOutside(ref, handler) {
  useEffect(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) handler();
    }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [ref, handler]);
}

function isoToEu(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

function euToIso(eu) {
  const trimmed = eu.trim();
  if (!trimmed) return null;
  const match = trimmed.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!match) return trimmed;
  return `${match[3]}-${match[2].padStart(2, '0')}-${match[1].padStart(2, '0')}`;
}

/* ── Floating popover ────────────────────────────────────────────────────── */
function Popover({ anchorRef, open, onClose, children }) {
  const popRef = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (open && anchorRef.current) {
      const r = anchorRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6, left: r.left });
    }
  }, [open, anchorRef]);

  useClickOutside(popRef, useCallback(() => { if (open) onClose(); }, [open, onClose]));

  if (!open) return null;
  return createPortal(
    <div ref={popRef} className="rp-popover" style={{ top: pos.top, left: pos.left }}>
      {children}
    </div>,
    document.body
  );
}

/* ── Type dropdown ───────────────────────────────────────────────────────── */
function TypeDropdown({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);
  const current = DOC_TYPES.find((d) => d.value === value) || DOC_TYPES[0];
  return (
    <div style={{ position: 'relative' }}>
      <button ref={btnRef} className={`rp-dropdown-btn${open ? ' open' : ''}`} onClick={() => setOpen((v) => !v)}>
        <span>{current.label}</span>
        <svg width="9" height="9" viewBox="0 0 10 6" fill="currentColor"><path d="M0 0l5 6 5-6z"/></svg>
      </button>
      <Popover anchorRef={btnRef} open={open} onClose={() => setOpen(false)}>
        {DOC_TYPES.map((dt) => (
          <div
            key={dt.label}
            className={`rp-popover-item${value === dt.value ? ' active' : ''}`}
            onClick={() => { onChange(dt.value); setOpen(false); }}
          >
            {dt.label}
          </div>
        ))}
      </Popover>
    </div>
  );
}

/* ── Date dropdown with custom popover ──────────────────────────────────── */
function DateDropdown({ filters, onChange }) {
  const [open, setOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const btnRef = useRef(null);
  const datePreset = filters._datePreset || null;
  const current = DATE_PRESETS.find((d) => d.value === datePreset) || DATE_PRESETS[0];

  function applyPreset(v) {
    if (v === '30d') {
      const d = new Date(); d.setDate(d.getDate() - 30);
      onChange({ ...filters, date_from: d.toISOString().split('T')[0], date_to: null, _datePreset: '30d' });
    } else if (v === '90d') {
      const d = new Date(); d.setDate(d.getDate() - 90);
      onChange({ ...filters, date_from: d.toISOString().split('T')[0], date_to: null, _datePreset: '90d' });
    } else if (v === 'custom') {
      onChange({ ...filters, date_from: null, date_to: null, _datePreset: 'custom' });
      setCustomOpen(true);
    } else {
      onChange({ ...filters, date_from: null, date_to: null, _datePreset: null });
    }
    setOpen(false);
  }

  return (
    <div style={{ position: 'relative' }}>
      <button ref={btnRef} className={`rp-dropdown-btn${open || customOpen ? ' open' : ''}`} onClick={() => setOpen((v) => !v)}>
        <span>{current.label}</span>
        <svg width="9" height="9" viewBox="0 0 10 6" fill="currentColor"><path d="M0 0l5 6 5-6z"/></svg>
      </button>

      {/* Preset dropdown */}
      <Popover anchorRef={btnRef} open={open} onClose={() => setOpen(false)}>
        {DATE_PRESETS.map((dp) => (
          <div
            key={dp.label}
            className={`rp-popover-item${datePreset === dp.value ? ' active' : ''}`}
            onClick={() => applyPreset(dp.value)}
          >
            {dp.label}
          </div>
        ))}
      </Popover>

      {/* Custom date popover */}
      <Popover anchorRef={btnRef} open={customOpen && !open} onClose={() => setCustomOpen(false)}>
        <div style={{ padding: '4px 0', minWidth: 220 }}>
          <div style={{ padding: '4px 12px 8px', fontSize: 11, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Custom date range
          </div>
          <div style={{ padding: '0 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 3 }}>From (dd.mm.yyyy)</div>
              <input
                type="text"
                value={isoToEu(filters.date_from)}
                onChange={(e) => onChange({ ...filters, date_from: euToIso(e.target.value) })}
                placeholder="dd.mm.yyyy"
                className="rp-date-input"
                style={{ width: '100%' }}
              />
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 3 }}>To (dd.mm.yyyy)</div>
              <input
                type="text"
                value={isoToEu(filters.date_to)}
                onChange={(e) => onChange({ ...filters, date_to: euToIso(e.target.value) })}
                placeholder="dd.mm.yyyy"
                className="rp-date-input"
                style={{ width: '100%' }}
              />
            </div>
            <button
              className="rp-popover-apply"
              onClick={() => setCustomOpen(false)}
            >
              Apply
            </button>
          </div>
        </div>
      </Popover>
    </div>
  );
}

/* ── Retrieval settings gear popover ─────────────────────────────────────── */
const DEPTH_OPTIONS = [
  { label: 'Low', value: 'low', desc: 'N=2 variations' },
  { label: 'Standard', value: 'standard', desc: 'N=3 (default)' },
  { label: 'Deep', value: 'deep', desc: 'N=5 variations' },
];

function RetrievalPopover({ retrieval, onChange }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);

  const isNonDefault = retrieval.depth !== 'standard' || retrieval.topK !== 10 || retrieval.scoreThreshold !== 0.60;

  function reset() {
    onChange({ depth: 'standard', topK: 10, scoreThreshold: 0.60 });
  }

  return (
    <div style={{ position: 'relative' }}>
      <Tooltip tip="Query depth, sources per variation, minimum relevance threshold" placement="below">
        <button
          ref={btnRef}
          className={`rp-gear-btn${isNonDefault ? ' active' : ''}`}
          onClick={() => setOpen((v) => !v)}
          aria-label="Retrieval settings"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          {isNonDefault && <span className="rp-gear-dot" />}
        </button>
      </Tooltip>
      <Popover anchorRef={btnRef} open={open} onClose={() => setOpen(false)}>
        <div style={{ padding: '12px 14px', minWidth: 240 }}>
          <div className="rp-popover-section-lbl">Query Depth</div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
            {DEPTH_OPTIONS.map((d) => (
              <Tooltip key={d.value} tip={d.desc} placement="below">
                <button
                  className={`pill${retrieval.depth === d.value ? ' on' : ''}`}
                  style={{ flex: 1 }}
                  onClick={() => onChange({ ...retrieval, depth: d.value })}
                >
                  {d.label}
                </button>
              </Tooltip>
            ))}
          </div>

          <div className="rp-popover-section-lbl">Sources per Variation (K={retrieval.topK})</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <button className="rp-stepper-btn" onClick={() => onChange({ ...retrieval, topK: Math.max(5, retrieval.topK - 1) })}>−</button>
            <span style={{ fontSize: 13, fontFamily: 'var(--mono)', minWidth: 20, textAlign: 'center' }}>{retrieval.topK}</span>
            <button className="rp-stepper-btn" onClick={() => onChange({ ...retrieval, topK: Math.min(20, retrieval.topK + 1) })}>+</button>
          </div>

          <div className="rp-popover-section-lbl">Min. Relevance ({retrieval.scoreThreshold.toFixed(2)})</div>
          <input
            type="range"
            min="0.40" max="0.90" step="0.05"
            value={retrieval.scoreThreshold}
            onChange={(e) => onChange({ ...retrieval, scoreThreshold: parseFloat(e.target.value) })}
            style={{ width: '100%', marginBottom: 12 }}
          />

          {isNonDefault && (
            <button
              onClick={reset}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent-l)', fontSize: 12, padding: 0 }}
            >
              Reset to defaults
            </button>
          )}
        </div>
      </Popover>
    </div>
  );
}

/* ── FilterBar ───────────────────────────────────────────────────────────── */

export default function FilterBar({ filters = {}, onChange, retrieval, onRetrievalChange }) {
  const activeAgency = filters.agency || 'All';

  function setAgency(v) {
    onChange?.({ ...filters, agency: v === 'All' ? null : v });
  }

  return (
    <div className="rp-filter">
      {/* Agency — compact button group */}
      <div className="grp">
        {AGENCIES.map((a) => (
          <Tooltip key={a} tip={a === 'All' ? 'No agency filter — search across all indexed regulators' : (AGENCY_TIPS[a] || '')} placement="below">
            <button className={`pill${activeAgency === a ? ' on' : ''}`} onClick={() => setAgency(a)}>
              {a}
            </button>
          </Tooltip>
        ))}
      </div>

      {/* Type — dropdown */}
      <div className="grp">
        <TypeDropdown value={filters.document_type || null} onChange={(v) => onChange?.({ ...filters, document_type: v })} />
      </div>

      {/* Date — dropdown with custom popover */}
      <div className="grp">
        <DateDropdown filters={filters} onChange={onChange} />
      </div>

      <div className="spacer" />

      {/* Retrieval — gear icon popover */}
      {retrieval && onRetrievalChange && (
        <RetrievalPopover retrieval={retrieval} onChange={onRetrievalChange} />
      )}
    </div>
  );
}
