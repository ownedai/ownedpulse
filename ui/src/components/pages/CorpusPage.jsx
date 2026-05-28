import { useState, useEffect, useCallback } from 'react';
import { getCorpusDocuments, getCorpusStats } from '../../api/client';
import DocumentViewer from './DocumentViewer';
import Tooltip from '../common/Tooltip';

const AGENCY_TABS = ['All', 'FDA', 'EMA', 'ICH'];
const DOC_TYPES = [
  { label: 'All', value: null },
  { label: 'Guidance', value: 'guidance' },
  { label: 'Press Release', value: 'press-release' },
  { label: 'Reflection Paper', value: 'reflection-paper' },
];

function formatDate(iso) {
  if (!iso) return 'Not available';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB');
}

export default function CorpusPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [agency, setAgency] = useState('All');
  const [docType, setDocType] = useState(null);
  const [offset, setOffset] = useState(0);
  const [viewerDoc, setViewerDoc] = useState(null);
  const limit = 50;

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = {
      limit,
      offset,
      agency: agency === 'All' ? null : agency,
      document_type: docType,
    };
    getCorpusDocuments(params)
      .then((data) => {
        setItems(data.items || []);
        setTotal(data.total || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agency, docType, offset]);

  useEffect(() => {
    getCorpusStats().then(setStats).catch(() => {});
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const lastRun = stats?.last_pipeline_run
    ? new Date(stats.last_pipeline_run).toLocaleDateString('en-GB') + ' ' +
      new Date(stats.last_pipeline_run).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    : '—';

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Corpus</h1>
          <p>All indexed regulatory documents.{' '}
            <Tooltip tip="Last time new regulatory documents were ingested via RSS">
              <span style={{ cursor: 'help' }}>Last pipeline run: {lastRun}</span>
            </Tooltip>
          </p>
        </div>
      </div>

      <div className="rp-table-wrap">
        {/* Agency tabs */}
        <div className="rp-tabs">
          {AGENCY_TABS.map((a) => (
            <Tooltip key={a} tip={a === 'All' ? 'Show all documents across all agencies' : 'Click to browse all documents from this agency'} placement="below">
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
                <td><span className="agency-mini">{doc.issuing_body}</span></td>
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
                  <button className="action" onClick={() => setViewerDoc(doc)}>View</button>
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
    </>
  );
}
