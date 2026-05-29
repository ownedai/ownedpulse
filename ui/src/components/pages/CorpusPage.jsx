import { useState, useEffect, useCallback } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { getCorpusDocumentsV2, getCorpusStats } from '../../api/client';
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
  { label: 'Safety Comms', value: 'safety-communication' },
  { label: 'Reg. Decision', value: 'regulatory-decision' },
  { label: 'News', value: 'news' },
  { label: 'Other', value: 'other' },
];
const STATUS_OPTS = [
  { label: 'All', value: null },
  { label: 'Indexed', value: 'indexed' },
  { label: 'Error', value: 'error' },
  { label: 'Superseded', value: 'superseded' },
  { label: 'Pending', value: 'pending' },
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
  const [docType, setDocType] = useState(null);
  const [status, setStatus] = useState(null);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  useEffect(() => {
    const a = searchParams.get('agency');
    setAgency(AGENCY_TABS.includes(a) ? a : 'All');
    setPage(1);
  }, [searchParams]);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = {
      page,
      page_size: pageSize,
      issuing_body: agency === 'All' ? null : agency,
      doc_type: docType,
      ingestion_status: status,
    };
    getCorpusDocumentsV2(params)
      .then((data) => {
        setItems(data.items || []);
        setTotal(data.total || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agency, docType, status, page]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    getCorpusStats().then(setStats).catch(() => {});
  }, []);

  const lastRun = stats?.last_pipeline_run
    ? formatDateTime(stats.last_pipeline_run)
    : '—';
  const totalPages = Math.ceil(total / pageSize);

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Corpus</h1>
          <p>All indexed regulatory documents. Last pipeline run: {lastRun}</p>
        </div>
      </div>

      <div className="rp-table-wrap">
        {/* Agency tabs */}
        <div className="rp-tabs">
          {AGENCY_TABS.map((a) => (
            <Tooltip key={a} tip={a === 'All' ? 'Show all documents across all agencies' : `${AGENCY_TIPS[a]} — click to browse all documents from this agency`} placement="below">
              <button
                className={`tab${agency === a ? ' on' : ''}`}
                onClick={() => { setAgency(a); setPage(1); }}
              >
                {a}
                {stats && a === 'All' && <span className="count">{stats.total_documents?.toLocaleString()}</span>}
                {stats && a !== 'All' && <span className="count">{stats.per_agency?.[a]?.toLocaleString() || '0'}</span>}
              </button>
            </Tooltip>
          ))}
        </div>

        {/* Doc type and status filters */}
        <div className="rp-filter-strip">
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>Type:</span>
          {DOC_TYPES.map((dt) => (
            <button
              key={dt.label}
              className={`pill${docType === dt.value ? ' on' : ''}`}
              onClick={() => { setDocType(dt.value); setPage(1); }}
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
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)', marginLeft: 8 }}>Status:</span>
          {STATUS_OPTS.map((s) => (
            <button
              key={s.label}
              className={`pill${status === s.value ? ' on' : ''}`}
              onClick={() => { setStatus(s.value); setPage(1); }}
              style={{
                fontFamily: 'var(--sans)',
                fontSize: 12.5,
                padding: '5px 11px',
                borderRadius: 3,
                cursor: 'pointer',
                background: status === s.value ? 'var(--accent-l)' : 'transparent',
                color: status === s.value ? '#fff' : 'var(--doc-text-2)',
                border: status === s.value ? '1px solid var(--accent-l)' : '1px solid transparent',
                fontWeight: status === s.value ? 500 : 400,
              }}
            >
              {s.label}
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
              <th style={{ width: 110 }}>Pub Date</th>
              <th style={{ width: 60 }}>Chunks</th>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 60 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && (
              <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>Loading...</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>No documents found.</td></tr>
            )}
            {items.map((doc) => {
              const isOk = doc.ingestion_status === 'indexed' || doc.ingestion_status === 'success';
              const isSuperseded = doc.ingestion_status === 'superseded';
              return (
                <tr key={doc.document_id}>
                  <td>
                    <Link to={`/corpus/${doc.document_id}`} className="truncate" title={doc.document_title} style={{ color: 'var(--accent-l)', fontSize: 13 }}>
                      {doc.document_title}
                    </Link>
                  </td>
                  <td>
                    <Tooltip tip={AGENCY_TIPS[doc.issuing_body] || doc.issuing_body}>
                      <span className="agency-mini" style={{ cursor: 'help' }}>{doc.issuing_body}</span>
                    </Tooltip>
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>{(doc.document_type || doc.doc_type || '—').replace(/-/g, ' ')}</td>
                  <td className="mono" style={{ fontSize: 11 }}>{doc.document_version || '—'}</td>
                  <td className="mono" style={{ fontSize: 11 }}>{formatDate(doc.publication_date)}</td>
                  <td className="mono">{doc.chunk_count || 0}</td>
                  <td>
                    {isSuperseded ? (
                      <span className="status warn">Superseded</span>
                    ) : isOk ? (
                      <span className="status ok">Current</span>
                    ) : (
                      <span className="status warn">{doc.ingestion_status || '—'}</span>
                    )}
                  </td>
                  <td>
                    {doc.source_url && (
                      <a href={doc.source_url} target="_blank" rel="noopener noreferrer" className="action" style={{ fontSize: 11 }}>
                        View ↗
                      </a>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div className="rp-pager">
            <span>{((page - 1) * pageSize) + 1}–{Math.min(page * pageSize, total)} of {total.toLocaleString()}</span>
            <div className="pages">
              <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>
                &larr;
              </button>
              <button onClick={() => setPage(page + 1)} disabled={page >= totalPages}>
                &rarr;
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
