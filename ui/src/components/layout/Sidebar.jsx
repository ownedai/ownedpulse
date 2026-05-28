import { Link } from 'react-router-dom';
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

export default function Sidebar({ activeQueryId, onNewQuery }) {
  const { items } = useHistory(10);
  const { stats } = useCorpusStats();

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

      <div className="grp-lbl">
        <span>Recent queries</span>
        <Link to="/history">View all &rarr;</Link>
      </div>

      <div className="rp-history">
        {items.map((h) => (
          <Link
            key={h.query_id}
            to={`/?q=${h.query_id}`}
            className={`item${h.query_id === activeQueryId ? ' active' : ''}`}
            style={{ textDecoration: 'none' }}
          >
            <div className="q">{h.query_text}</div>
            <div className="t">{relativeTime(h.timestamp)}</div>
          </Link>
        ))}
      </div>

      <div className="rp-status">
        <div className="grp-lbl" style={{ padding: 0, marginBottom: 8 }}>System</div>
        <div className="row">
          <span className="k">Pipeline</span>
          <span className="v ok">
            {stats?.last_pipeline_run
              ? formatDateTime(stats.last_pipeline_run)
              : '—'}
          </span>
        </div>
        <div className="row">
          <span className="k">Docs indexed</span>
          <span className="v">{stats?.total_documents?.toLocaleString() || '—'}</span>
        </div>
        <div className="row">
          <span className="k">Embed model</span>
          <span className="v">mxbai-embed-large</span>
        </div>
        <div className="row">
          <span className="k">Build</span>
          <span className="v">v0.7.0</span>
        </div>
      </div>
    </aside>
  );
}
