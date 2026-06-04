import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation } from 'react-router-dom';
import Logo from '../common/Logo';
import useHistory from '../../hooks/useHistory';
import useCorpusStats from '../../hooks/useCorpusStats';
import { formatDate, formatDateTime } from '../../dateFormat';
import { getAppVersion, getAdminModels, updateActiveModel } from '../../api/client';

function relativeTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = now - d;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return formatDate(iso);
}

function isNavActive(to, pathname) {
  if (to === '/corpus') {
    return pathname === '/corpus' || (pathname.startsWith('/corpus/') && !pathname.startsWith('/corpus/runs'));
  }
  return pathname === to || pathname.startsWith(to + '/');
}
// /corpus/runs redirects to /ingestions — mark ingestions active for both paths

const SearchIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
  </svg>
);
const DatabaseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>
  </svg>
);
const LayersIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
  </svg>
);
const ClockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
  </svg>
);
const SettingsIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3"/>
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
  </svg>
);

const SwapIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 16V4m0 0L3 8m4-4l4 4"/><path d="M17 8v12m0 0l4-4m-4 4l-4-4"/>
  </svg>
);

function ModelPickerModal({ current, onClose, onChanged }) {
  const [models, setModels] = useState([]);
  const [selected, setSelected] = useState(current);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getAdminModels()
      .then(d => {
        setModels(d.available_models || []);
        setSelected(d.active_model || current);
        setLoading(false);
      })
      .catch(() => {
        setError('Could not reach Ollama');
        setLoading(false);
      });
  }, [current]);

  async function handleApply() {
    if (!selected || selected === current) { onClose(); return; }
    setSaving(true);
    setError(null);
    try {
      await updateActiveModel(selected);
      setDone(true);
      onChanged(selected);
      setTimeout(onClose, 1400);
    } catch (e) {
      setError(e.message || 'Failed to update model');
      setSaving(false);
    }
  }

  return createPortal(
    <div className="rp-modal-back" onClick={onClose}>
      <div className="rp-model-modal" onClick={e => e.stopPropagation()}>
        <div className="rp-model-modal-hd">
          <span>Change LLM model</span>
          <button className="rp-model-modal-x" onClick={onClose}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {loading && <div className="rp-model-modal-msg muted">Loading available models…</div>}
        {!loading && error && <div className="rp-model-modal-msg err">{error}</div>}

        {!loading && !error && !done && (
          <div className="rp-model-modal-list">
            {models.map(m => (
              <div
                key={m}
                className={`rp-model-row${selected === m ? ' sel' : ''}`}
                onClick={() => setSelected(m)}
              >
                <span className="rp-model-radio">{selected === m ? '●' : '○'}</span>
                <span className="rp-model-name">{m}</span>
                {m === current && <span className="rp-model-active-badge">active</span>}
              </div>
            ))}
          </div>
        )}

        {done && (
          <div className="rp-model-modal-msg ok">
            ✓ Switched to {selected} — loading into Ollama…
          </div>
        )}

        {!loading && !done && (
          <div className="rp-model-modal-ft">
            <button className="rp-model-btn cancel" onClick={onClose} disabled={saving}>Cancel</button>
            <button
              className="rp-model-btn apply"
              onClick={handleApply}
              disabled={saving || !selected || selected === current}
            >
              {saving ? 'Applying…' : 'Apply'}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

const NAV_ITEMS = [
  { to: '/history', label: 'Query Log', Icon: SearchIcon },
  { to: '/corpus', label: 'Corpus', Icon: DatabaseIcon },
  { to: '/sources', label: 'Sources', Icon: LayersIcon },
  { to: '/ingestions', label: 'Ingestions', Icon: ClockIcon },
  { to: '/admin', label: 'Admin', Icon: SettingsIcon, separator: true },
];

export default function Sidebar({ onNewQuery, modelStatus = {} }) {
  const { pathname } = useLocation();
  const { items } = useHistory(5);
  const { stats } = useCorpusStats();
  const isQueryPage = pathname === '/';
  const [appVersion, setAppVersion] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    getAppVersion().then((d) => setAppVersion(d.version)).catch(() => {});
  }, []);

  function handleModelChanged(newModel) {
    modelStatus.recheck?.();
  }

  return (
    <aside className="rp-sidebar">
      <div className="brand">
        <Logo showWordmark />
      </div>

      <button className="newq" onClick={onNewQuery}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M8 3v10M3 8h10" />
        </svg>
        New query
      </button>

      <nav className="rp-nav">
        {NAV_ITEMS.map(({ to, label, Icon, separator }) => (
          <div key={to}>
            {separator && <div className="rp-nav-sep" />}
            <Link
              to={to}
              className={`rp-nav-item${isNavActive(to, pathname) ? ' active' : ''}`}
            >
              <Icon />
              {label}
            </Link>
          </div>
        ))}
      </nav>

      {isQueryPage && (
        <>
          <div className="grp-lbl">
            <span>Recent queries</span>
            <Link to="/history">View all &rarr;</Link>
          </div>
          <div className="rp-history">
            {items.slice(0, 5).map((h) => (
              <Link
                key={h.query_id}
                to={`/?q=${h.query_id}`}
                className="item"
                style={{ textDecoration: 'none' }}
              >
                <div className="q">{h.query_text}</div>
                <div className="t">{relativeTime(h.timestamp)}</div>
              </Link>
            ))}
          </div>
        </>
      )}

      <div className="rp-status">
        <div className="rp-status-section-lbl">System</div>


        <div className="row rp-llm-row">
          <span className="k" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            LLM
            <button
              className="rp-model-swap-btn"
              title="Change model"
              onClick={() => setPickerOpen(true)}
            >
              <SwapIcon />
            </button>
          </span>
          <span className="v" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span
              className={`rp-model-dot${modelStatus.loaded ? ' loaded' : ''}`}
              title={modelStatus.loaded ? 'Model loaded' : 'Loading model…'}
            />
            {modelStatus.model || 'phi4:14b-q8'}
          </span>
        </div>
        {pickerOpen && (
          <ModelPickerModal
            current={modelStatus.model}
            onClose={() => setPickerOpen(false)}
            onChanged={handleModelChanged}
          />
        )}
        <div className="row">
          <span className="k">Embed</span>
          <span className="v" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span
              className={`rp-model-dot${modelStatus.embed_loaded ? ' loaded' : ''}`}
              title={modelStatus.embed_loaded ? 'Embedding model loaded' : 'Loading embedding model…'}
            />
            {modelStatus.embed_model || 'mxbai-embed-large'}
          </span>
        </div>
        <div className="row">
          <span className="k">Build</span>
          <span className="v">{appVersion ? `v${appVersion}` : '…'}</span>
        </div>
      </div>
    </aside>
  );
}
