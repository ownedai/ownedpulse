import { Link, useLocation } from 'react-router-dom';
import Logo from '../common/Logo';
import useHistory from '../../hooks/useHistory';
import useCorpusStats from '../../hooks/useCorpusStats';
import { formatDate, formatDateTime } from '../../dateFormat';

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

const NAV_ITEMS = [
  { to: '/history', label: 'Query Log', Icon: SearchIcon },
  { to: '/corpus', label: 'Corpus', Icon: DatabaseIcon },
  { to: '/corpus/runs', label: 'Run Log', Icon: ClockIcon },
  { to: '/admin', label: 'Admin', Icon: SettingsIcon, separator: true },
];

export default function Sidebar({ onNewQuery, modelStatus = {} }) {
  const { pathname } = useLocation();
  const { items } = useHistory(5);
  const { stats } = useCorpusStats();
  const isQueryPage = pathname === '/';

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


        <div className="row">
          <span className="k">LLM</span>
          <span className="v" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span
              className={`rp-model-dot${modelStatus.loaded ? ' loaded' : ''}`}
              title={modelStatus.loaded ? 'Model loaded' : 'Loading model…'}
            />
            {modelStatus.model || 'phi4:14b-q8'}
          </span>
        </div>
        <div className="row">
          <span className="k">Embed</span>
          <span className="v">mxbai-embed-large</span>
        </div>
        <div className="row">
          <span className="k">Build</span>
          <span className="v">v0.7.01</span>
        </div>
      </div>
    </aside>
  );
}
