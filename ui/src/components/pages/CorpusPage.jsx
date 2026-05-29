import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { createPortal } from 'react-dom';
import { getCorpusDocumentsV2, getCorpusStats } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

const AGENCY_TABS = ['All', 'FDA', 'EMA', 'ICH'];
const DOC_TYPES = [
  { label: 'All types', value: null },
  { label: 'Guidance', value: 'guidance' },
  { label: 'Press Release', value: 'press-release' },
  { label: 'Reflection Paper', value: 'reflection-paper' },
  { label: 'Safety Comms', value: 'safety-communication' },
  { label: 'Regulatory Decision', value: 'regulatory-decision' },
  { label: 'News', value: 'news' },
  { label: 'Other', value: 'other' },
];
const STATUS_OPTS = [
  { label: 'All statuses', value: null },
  { label: 'Indexed', value: 'indexed' },
  { label: 'Processing', value: 'pending' },
  { label: 'Error', value: 'error' },
  { label: 'Superseded', value: 'superseded' },
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

function FilterDropdown({ options, value, onChange }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useClickOutside(popRef, () => { if (open) setOpen(false); });

  const current = options.find((o) => o.value === value) || options[0];

  function handleOpen() {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left });
    }
    setOpen((v) => !v);
  }

  return (
    <>
      <button
        ref={btnRef}
        className={`rp-dropdown-btn${open ? ' open' : ''}`}
        onClick={handleOpen}
        style={{ fontSize: 12.5 }}
      >
        <span>{current.label}</span>
        <svg width="9" height="9" viewBox="0 0 10 6" fill="currentColor"><path d="M0 0l5 6 5-6z"/></svg>
      </button>
      {open && createPortal(
        <div ref={popRef} className="rp-popover" style={{ position: 'fixed', top: pos.top, left: pos.left, minWidth: 160 }}>
          {options.map((o) => (
            <div
              key={o.label}
              className={`rp-popover-item${value === o.value ? ' active' : ''}`}
              onClick={() => { onChange(o.value); setOpen(false); }}
            >
              {o.label}
            </div>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}

function StatusBadge({ status }) {
  const isOk = status === 'indexed' || status === 'success';
  const isError = status === 'error';
  const isProcessing = status === 'pending' || status === 'processing';
  const isSuperseded = status === 'superseded';

  if (isOk) return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ok-text)', border: '1px solid var(--ok-tint-border)', background: 'var(--ok-tint)', padding: '2px 7px', borderRadius: 3 }}>
      <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--ok)', flexShrink: 0 }} />
      INDEXED
    </span>
  );
  if (isError) return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--err-text)', border: '1px solid var(--err-tint-border)', background: 'var(--err-tint)', padding: '2px 7px', borderRadius: 3 }}>
      <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--err)', flexShrink: 0 }} />
      ERROR
    </span>
  );
  if (isProcessing) return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--warn-text)', border: '1px solid var(--warn-tint-border)', background: 'var(--warn-tint)', padding: '2px 7px', borderRadius: 3 }}>
      <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--warn)', flexShrink: 0 }} />
      PROCESSING
    </span>
  );
  if (isSuperseded) return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-2)', border: '1px solid var(--doc-border)', padding: '2px 7px', borderRadius: 3 }}>
      SUPERSEDED
    </span>
  );
  return <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--doc-text-3)' }}>{status || '—'}</span>;
}

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
  const [search, setSearch] = useState('');
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

  const totalPages = Math.ceil(total / pageSize);

  const filteredItems = search
    ? items.filter((d) =>
        (d.document_title || '').toLowerCase().includes(search.toLowerCase()) ||
        (d.document_id || '').toLowerCase().includes(search.toLowerCase())
      )
    : items;

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Corpus</h1>
        </div>
      </div>

      <div className="rp-table-wrap">
        {/* Filter row */}
        <div className="rp-filter-strip">
          <input
            type="text"
            placeholder="Search documents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              height: 30,
              padding: '0 10px',
              fontSize: 12.5,
              fontFamily: 'var(--sans)',
              background: 'var(--doc-surface)',
              border: '1px solid var(--doc-border)',
              borderRadius: 3,
              color: 'var(--doc-text)',
              outline: 'none',
              width: 200,
            }}
          />
          <FilterDropdown
            options={[{ label: 'All bodies', value: null }, ...AGENCY_TABS.filter((a) => a !== 'All').map((a) => ({ label: a, value: a }))]}
            value={agency === 'All' ? null : agency}
            onChange={(v) => { setAgency(v || 'All'); setPage(1); }}
          />
          <FilterDropdown
            options={DOC_TYPES}
            value={docType}
            onChange={(v) => { setDocType(v); setPage(1); }}
          />
          <FilterDropdown
            options={STATUS_OPTS}
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
          />
          <div style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
            {total.toLocaleString()} documents
          </span>
        </div>

        {/* Table */}
        <table className="rp-table">
          <thead>
            <tr>
              <th style={{ width: 130 }}>Document ID</th>
              <th>Title</th>
              <th style={{ width: 60 }}>Version</th>
              <th style={{ width: 70 }}>Agency</th>
              <th style={{ width: 110 }}>Type</th>
              <th style={{ width: 100 }}>Published ↓</th>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 60 }}>Chunks</th>
              <th style={{ width: 120 }}>Last Indexed</th>
            </tr>
          </thead>
          <tbody>
            {loading && filteredItems.length === 0 && (
              <tr><td colSpan={9} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>Loading...</td></tr>
            )}
            {!loading && filteredItems.length === 0 && (
              <tr><td colSpan={9} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>No documents found.</td></tr>
            )}
            {filteredItems.map((doc) => (
              <tr key={doc.document_id}>
                <td>
                  <Link
                    to={`/corpus/${doc.document_id}`}
                    style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent-l)', letterSpacing: '-0.02em' }}
                    title={doc.document_id}
                  >
                    {doc.document_id}
                  </Link>
                </td>
                <td style={{ fontSize: 13, color: 'var(--doc-text)' }} className="truncate" title={doc.document_title}>
                  {doc.document_title}
                </td>
                <td className="mono" style={{ fontSize: 11 }}>{doc.document_version || '—'}</td>
                <td className="mono" style={{ fontSize: 11 }}>{doc.issuing_body}</td>
                <td className="mono" style={{ fontSize: 11 }}>{(doc.document_type || doc.doc_type || '—').replace(/-/g, ' ')}</td>
                <td className="mono" style={{ fontSize: 11 }}>{formatDate(doc.publication_date)}</td>
                <td><StatusBadge status={doc.ingestion_status} /></td>
                <td className="mono">{doc.chunk_count || 0}</td>
                <td className="mono" style={{ fontSize: 10 }}>{doc.last_indexed_at ? formatDateTime(doc.last_indexed_at) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div className="rp-pager">
            <span>{((page - 1) * pageSize) + 1}–{Math.min(page * pageSize, total)} of {total.toLocaleString()}</span>
            <div className="pages">
              <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>&larr;</button>
              <button onClick={() => setPage(page + 1)} disabled={page >= totalPages}>&rarr;</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
