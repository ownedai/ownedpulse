import { Link } from 'react-router-dom';
import Tooltip from '../common/Tooltip';
import useCorpusStats from '../../hooks/useCorpusStats';
import { useBootstrapProgress, stopBootstrapTracking } from '../../hooks/useBootstrapProgress';
import { formatDateTime } from '../../dateFormat';
import { useState, useCallback, useEffect } from 'react';

function SpinnerIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 11-6.219-8.56" style={{ transformOrigin: '12px 12px', animation: 'spin 1s linear infinite' }} />
    </svg>
  );
}

export default function CorpusStatsBar() {
  const { stats } = useCorpusStats();
  const { uiMode, progress, docEvents } = useBootstrapProgress();
  const [contextMenu, setContextMenu] = useState(null);
  const isRunning = uiMode === 'running' || stats?.ingestion_active;

  const handleContext = useCallback((e) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }, []);

  const handleStop = useCallback(async () => {
    if (uiMode === 'running') {
      stopBootstrapTracking();
    } else if (stats?.ingestion_active) {
      try { await fetch('/api/admin/stop-ingestion', { method: 'POST' }); } catch (_) {}
    }
    setContextMenu(null);
  }, [uiMode, stats?.ingestion_active]);

  const closeMenu = useCallback(() => setContextMenu(null), []);

  useEffect(() => {
    if (!contextMenu) return;
    const handler = () => closeMenu();
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, [contextMenu, closeMenu]);

  if (!stats && !isRunning) return null;

  const lastRun = stats?.last_pipeline_run
    ? formatDateTime(stats.last_pipeline_run)
    : '—';

  const pct = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
  const eta = progress.eta_seconds > 0
    ? progress.eta_seconds < 60 ? '<1m' : progress.eta_seconds < 3600 ? `~${Math.round(progress.eta_seconds / 60)}m` : `~${(progress.eta_seconds / 3600).toFixed(1)}h`
    : '—';

  return (
    <div className="rp-corpus-bar" data-testid="corpus-stats-bar">
      <div className="left">
        {stats && (
          <>
            <Tooltip tip="Total guidance documents currently indexed in the regpulse vector store.">
              <span className="stat" style={{ cursor: 'help' }}>
                <span className="k">Indexed</span>
                <span className="v">{stats.total_documents?.toLocaleString() || '—'} docs</span>
              </span>
            </Tooltip>
            <Tooltip tip="U.S. Food & Drug Administration — click to browse all FDA documents in the corpus.">
              <span className="stat">
                <span className="k">FDA</span>
                <Link to="/corpus?agency=FDA" data-testid="corpus-stats-fda">
                  {stats.per_agency?.FDA || 0}
                </Link>
              </span>
            </Tooltip>
            <Tooltip tip="European Medicines Agency — click to browse all EMA documents in the corpus.">
              <span className="stat">
                <span className="k">EMA</span>
                <Link to="/corpus?agency=EMA" data-testid="corpus-stats-ema">
                  {stats.per_agency?.EMA || 0}
                </Link>
              </span>
            </Tooltip>
            <Tooltip tip="International Council for Harmonisation — click to browse all ICH documents in the corpus.">
              <span className="stat">
                <span className="k">ICH</span>
                <Link to="/corpus?agency=ICH" data-testid="corpus-stats-ich">
                  {stats.per_agency?.ICH || 0}
                </Link>
              </span>
            </Tooltip>
          </>
        )}
      </div>

      <div className="right">
        {isRunning && (
          <div
            className="ingestion-status"
            onClick={() => window.dispatchEvent(new CustomEvent('regpulse:open-progress'))}
            onContextMenu={handleContext}
            style={{ cursor: 'pointer' }}
            title={uiMode === 'running'
              ? `Bootstrap: ${progress.processed} / ${progress.total} docs — ETA: ${eta}`
              : `Source ingestion running — ${stats?.ingestion_detail || ''}`}
          >
            <SpinnerIcon />
            {uiMode === 'running' ? (
              <span className="ingestion-pct">{pct}%</span>
            ) : (
              <span className="ingestion-label">ING</span>
            )}
          </div>
        )}
        <Tooltip tip="Last time new regulatory documents were automatically checked and ingested via the source pipeline.">
          <span className="stat" style={{ cursor: 'help' }}>
            <span className="k">KB last updated</span>
            <span className="v" data-testid="last-pipeline-run">{lastRun}</span>
          </span>
        </Tooltip>
      </div>

      {contextMenu && (
        <div
          className="ingestion-context-menu"
          style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y - 80, zIndex: 10000 }}
          onClick={closeMenu}
        >
          <button onClick={handleStop}>Stop ingestion</button>
        </div>
      )}
    </div>
  );
}
