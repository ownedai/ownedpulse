import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getCorpusDocuments, getCorpusStats } from '../../api/client';
import DocumentViewer from './DocumentViewer';
import CorpusStatsBar from '../query/CorpusStatsBar';
import Tooltip from '../common/Tooltip';
import { formatDate, formatDateTime } from '../../dateFormat';

const AGENCY_TABS = ['All', 'FDA', 'EMA', 'ICH'];
const AGENCY_TIPS = {
  FDA: 'U.S. Food & Drug Administration',
  EMA: 'European Medicines Agency',
  ICH: 'International Council for Harmonisation',
};
const DOC_TYPES = [
  { label: 'All', value: null },
  { label: 'Guidance', value: 'guidance' },
  { label: 'Press Release', value: 'press-release' },
  { label: 'Reflection Paper', value: 'reflection-paper' },
];

export default function CorpusPage() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [agency, setAgency] = useState(() => {
    const a = searchParams.get('agency');
    return AGENCY_TABS.includes(a) ? a : 'All';
  });

  useEffect(() => {
    const a = searchParams.get('agency');
    setAgency(AGENCY_TABS.includes(a) ? a : 'All');
    setOffset(0);
  }, [searchParams]);
  const [docType, setDocType] = useState(null);
  const [offset, setOffset] = useState(0);
  const [showFeeds, setShowFeeds] = useState(false);
  const [viewerDoc, setViewerDoc] = useState(null);
  const limit = 50;

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = {
      limit,
      offset,
      agency: agency === 'All' ? null : agency,
      document_type: docType,
      exclude_feeds: showFeeds ? 'false' : 'true',
    };
    getCorpusDocuments(params)
      .then((data) => {
        setItems(data.documents || []);
        setTotal(data.total || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agency, docType, offset, showFeeds]);

  useEffect(() => {
    getCorpusStats().then(setStats).catch(() => {});
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const lastRun = stats?.last_pipeline_run
    ? formatDateTime(stats.last_pipeline_run)
    : '—';

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Corpus</h1>
          <p>All indexed regulatory documents.</p>
        </div>
      </div>

      <div className="rp-table-wrap">
        {/* Agency tabs */}
        <div className="rp-tabs">
          {AGENCY_TABS.map((a) => (
            <Tooltip key={a} tip={a === 'All' ? 'Show all documents across all agencies' : `${AGENCY_TIPS[a]} — click to browse all documents from this agency`} placement="below">
              <button
                className={`tab${agency === a ? ' on' : ''}`}
                onClick={() => { setAgency(a); setOffset(0); }}
              >
                {a}
                {stats && a === 'All' && <span className="count">{stats.total_documents?.toLocaleString()}</span>}
                {stats && a !== 'All' && <span className="count">{stats.per_agency?.[a]?.toLocaleString() || '0'}</span>}
              </button>
            </Tooltip>
          ))}
        </div>

        {/* Doc type filter */}
        <div className="rp-filter-strip">
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>Type:</span>
          {DOC_TYPES.map((dt) => (
            <button
              key={dt.label}
              className={`pill${docType === dt.value ? ' on' : ''}`}
              onClick={() => { setDocType(dt.value); setOffset(0); }}
              style={{
                fontFamily: 'var(--sans)',
                fontSize: 12.5,
                padding: '5px 11px',
                borderRadius: 3,
                cursor: 'pointer',
                background: docType === dt.value ? 'var(--accent-l)' : 'transparent',
                color: docType === dt.value ? '#fff' : 'var(--doc-text-2)',
                border: docType === dt.value ? '1px solid var(--accent-l)' : '1px solid transparent',
                fontWeight: docType === dt.value ? 500 : 400,
              }}
            >
              {dt.label}
            </button>
          ))}
          <div className="spacer" style={{ flex: 1 }} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)', cursor: 'pointer', userSelect: 'none' }}>
            <input
              type="checkbox"
              checked={showFeeds}
              onChange={(e) => { setShowFeeds(e.target.checked); setOffset(0); }}
              style={{ accentColor: 'var(--accent-l)', cursor: 'pointer' }}
            />
            Show feed items
          </label>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
            {total.toLocaleString()} documents
          </span>
        </div>

        {/* Table */}
        <table className="rp-table">
          <thead>
            <tr>
              <th>Title</th>
              <th style={{ width: 80 }}>Agency</th>
              <th style={{ width: 120 }}>Doc Type</th>
              <th style={{ width: 80 }}>Version</th>
              <th style={{ width: 110 }}>Publication Date</th>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 80 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>
                  Loading...
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>
                  No documents found.
                </td>
              </tr>
            )}
            {items.map((doc) => (
              <tr key={doc.document_id}>
                <td>
                  <span className="truncate" title={doc.document_title}>{doc.document_title}</span>
                </td>
                <td>
                  <Tooltip tip={AGENCY_TIPS[doc.issuing_body] || doc.issuing_body}>
                    <span className="agency-mini" style={{ cursor: 'help' }}>{doc.issuing_body}</span>
                  </Tooltip>
                </td>
                <td className="mono">{doc.doc_type?.replace(/_/g, ' ') || '—'}</td>
                <td className="mono">{doc.document_version || '—'}</td>
                <td className="mono">{formatDate(doc.publication_date)}</td>
                <td>
                  {doc.superseded ? (
                    <span className="status warn">Superseded</span>
                  ) : (
                    <span className="status ok">Current</span>
                  )}
                </td>
                <td>
                  {doc.source_file_format === 'html' || !doc.source_local_path ? (
                    <button
                      className="action"
                      onClick={() => doc.source_url && window.open(doc.source_url, '_blank', 'noopener,noreferrer')}
                      disabled={!doc.source_url}
                      title={doc.source_url || 'No source URL available'}
                    >
                      View ↗
                    </button>
                  ) : (
                    <button className="action" onClick={() => setViewerDoc(doc)}>View</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="rp-pager">
          <span>{offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString()}</span>
          <div className="pages">
            <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}>
              &larr;
            </button>
            <button onClick={() => setOffset(offset + limit)} disabled={offset + limit >= total}>
              &rarr;
            </button>
          </div>
        </div>
      </div>

      {viewerDoc && (
        <DocumentViewer document={viewerDoc} onClose={() => setViewerDoc(null)} />
      )}

      <CorpusStatsBar />
    </>
  );
}
