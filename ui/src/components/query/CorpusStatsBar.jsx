import { Link } from 'react-router-dom';
import Tooltip from '../common/Tooltip';
import useCorpusStats from '../../hooks/useCorpusStats';

export default function CorpusStatsBar() {
  const { stats } = useCorpusStats();

  if (!stats) return null;

  const lastRun = stats.last_pipeline_run
    ? new Date(stats.last_pipeline_run).toLocaleDateString('en-GB') + ' ' +
      new Date(stats.last_pipeline_run).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : '—';

  return (
    <div className="rp-corpus-bar" data-testid="corpus-stats-bar">
      <div className="left">
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
      </div>

      <div className="right">
        <Tooltip tip="Last time new regulatory documents were automatically checked and ingested via the RSS feed pipeline.">
          <span className="stat" style={{ cursor: 'help' }}>
            <span className="k">Last updated</span>
            <span className="v" data-testid="last-pipeline-run">{lastRun}</span>
          </span>
        </Tooltip>
      </div>
    </div>
  );
}
