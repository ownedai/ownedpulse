import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { createPortal } from 'react-dom';
import { getCorpusDocumentsV2 } from '../../api/client';
import { formatDate } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';

const AGENCY_OPTS = [
  { label: 'All bodies', value: null },
  { label: 'FDA', value: 'FDA' },
  { label: 'EMA', value: 'EMA' },
  { label: 'ICH', value: 'ICH' },
];
const DOC_TYPES = [
  { label: 'All types', value: null },
  { label: 'Guidance', value: 'guidance' },
  { label: 'Drug Approval', value: 'drug_approval' },
  { label: 'Press Release', value: 'press_release' },
  { label: 'Reflection Paper', value: 'reflection_paper' },
  { label: 'Safety Alert', value: 'safety_alert' },
  { label: 'News', value: 'news_item' },
  { label: 'Other', value: 'other' },
];
const STATUS_OPTS = [
  { label: 'All statuses', value: null },
  { label: 'Indexed', value: 'indexed' },
  { label: 'Processing', value: 'pending' },
  { label: 'Error', value: 'error' },
  { label: 'Superseded', value: 'superseded' },
];
const DOC_TYPE_LABELS = {
  guidance_pdf: 'Guidance', guidance: 'Guidance',
  press_release: 'Press Release', reflection_paper: 'Reflection Paper',
  drug_approval: 'Drug Approval', safety_alert: 'Safety Alert',
  news_item: 'News', other: 'Other',
};

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
      <button ref={btnRef} className={`rp-dropdown-btn${open ? ' open' : ''}`} onClick={handleOpen} style={{ fontSize: 12.5 }}>
        <span>{current.label}</span>
        <svg width="9" height="9" viewBox="0 0 10 6" fill="currentColor"><path d="M0 0l5 6 5-6z"/></svg>
      </button>
      {open && createPortal(
        <div ref={popRef} className="rp-popover" style={{ position: 'fixed', top: pos.top, left: pos.left, minWidth: 160 }}>
          {options.map((o) => (
            <div key={o.label} className={`rp-popover-item${value === o.value ? ' active' : ''}`} onClick={() => { onChange(o.value); setOpen(false); }}>
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
  const c = getStatusConfig(status);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      padding: '2px 7px', borderRadius: 2,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
    }}>
      {c.label}
    </span>
  );
}

function Pager({ page, pageSize, total, onPage, onPageSize }) {
  const totalPages = Math.ceil(total / pageSize);
  if (total === 0) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  // Sliding window of up to 7 page buttons
  let pages = [];
  if (totalPages <= 7) {
    pages = Array.from({ length: totalPages }, (_, i) => i + 1);
  } else {
    const left = Math.max(1, page - 3);
    const right = Math.min(totalPages, left + 6);
    pages = Array.from({ length: right - left + 1 }, (_, i) => left + i);
  }

  return (
    <div className="rp-pager">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'var(--doc-text-3)' }}>Rows:</span>
        <div style={{ display: 'inline-flex', border: '1px solid var(--doc-border)', borderRadius: 3, overflow: 'hidden' }}>
          {[25, 50, 100].map((n) => (
            <button
              key={n}
              onClick={() => { onPageSize(n); onPage(1); }}
              style={{
                background: pageSize === n ? 'var(--accent-l)' : 'var(--doc-surface)',
                border: 'none',
                borderRight: '1px solid var(--doc-border)',
                color: pageSize === n ? '#fff' : 'var(--doc-text-2)',
                fontFamily: 'var(--mono)', fontSize: 11,
                padding: '3px 9px', cursor: 'pointer',
              }}
            >{n}</button>
          ))}
        </div>
        <span style={{ color: 'var(--doc-text-2)', marginLeft: 8 }}>{start}–{end} of {total.toLocaleString()}</span>
      </div>
      <div className="pages">
        <button onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1}>←</button>
        {pages[0] > 1 && <button onClick={() => onPage(1)}>1</button>}
        {pages[0] > 2 && <button disabled>…</button>}
        {pages.map((p) => (
          <button key={p} className={p === page ? 'on' : ''} onClick={() => onPage(p)}>{p}</button>
        ))}
        {pages[pages.length - 1] < totalPages - 1 && <button disabled>…</button>}
        {pages[pages.length - 1] < totalPages && <button onClick={() => onPage(totalPages)}>{totalPages}</button>}
        <button onClick={() => onPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages}>→</button>
      </div>
    </div>
  );
}

export default function CorpusPage() {
  const [searchParams] = useSearchParams();

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const [agency, setAgency] = useState(() => {
    const a = searchParams.get('agency');
    return ['FDA', 'EMA', 'ICH'].includes(a) ? a : null;
  });
  const [docType, setDocType] = useState(() => searchParams.get('doc_type') || null);
  const [status, setStatus] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  useEffect(() => {
    const a = searchParams.get('agency');
    const dt = searchParams.get('doc_type');
    setAgency(['FDA', 'EMA', 'ICH'].includes(a) ? a : null);
    setDocType(dt || null);
    setPage(1);
  }, [searchParams]);

  const fetchData = useCallback(() => {
    setLoading(true);
    getCorpusDocumentsV2({ page, page_size: pageSize, issuing_body: agency, doc_type: docType, ingestion_status: status })
      .then((data) => { setItems(data.items || []); setTotal(data.total || 0); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agency, docType, status, page, pageSize]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filteredItems = search
    ? items.filter((d) =>
        (d.document_title || '').toLowerCase().includes(search.toLowerCase()) ||
        (d.document_id || '').toLowerCase().includes(search.toLowerCase())
      )
    : items;

  return (
    <>
      <div className="rp-page-head">
        <h1>Corpus</h1>
      </div>

      <div className="rp-table-wrap">
        <div className="rp-filter-strip">
          <input
            type="text"
            placeholder="Search documents…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            style={{
              height: 30, padding: '0 10px', fontSize: 12.5,
              fontFamily: 'var(--sans)', background: 'var(--doc-surface)',
              border: '1px solid var(--doc-border)', borderRadius: 3,
              color: 'var(--doc-text)', outline: 'none', width: 200,
            }}
          />
          <FilterDropdown options={AGENCY_OPTS} value={agency} onChange={(v) => { setAgency(v); setPage(1); }} />
          <FilterDropdown options={DOC_TYPES} value={docType} onChange={(v) => { setDocType(v); setPage(1); }} />
          <FilterDropdown options={STATUS_OPTS} value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
        </div>

        <table className="rp-table" style={{ fontSize: 12.5 }}>
          <thead>
            <tr>
              <th>Document</th>
              <th style={{ width: 55 }}>Agency</th>
              <th style={{ width: 110 }}>Type</th>
              <th style={{ width: 70 }}>Version</th>
              <th style={{ width: 95 }}>Published</th>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 55, textAlign: 'right' }}>Chunks</th>
            </tr>
          </thead>
          <tbody>
            {loading && filteredItems.length === 0 && (
              <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 12 }}>Loading…</td></tr>
            )}
            {!loading && filteredItems.length === 0 && (
              <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 12 }}>No documents found.</td></tr>
            )}
            {filteredItems.map((doc) => (
              <tr key={doc.document_id}>
                <td>
                  <Link
                    to={`/corpus/${encodeURIComponent(doc.document_id)}`}
                    title={doc.document_id}
                    style={{ fontSize: 12.5, color: 'var(--accent-l)', textDecoration: 'none', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {doc.document_title || doc.document_id}
                  </Link>
                </td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
                  {doc.issuing_body === 'EU-Commission' ? 'EMA' : (doc.issuing_body || '—')}
                </td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
                  {DOC_TYPE_LABELS[doc.doc_type] || DOC_TYPE_LABELS[doc.document_type] || (doc.doc_type || '—').replace(/_/g, ' ')}
                </td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.document_version || '—'}</td>
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{formatDate(doc.publication_date)}</td>
                <td><StatusBadge status={doc.ingestion_status} /></td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.chunk_count || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <Pager page={page} pageSize={pageSize} total={search ? filteredItems.length : total} onPage={setPage} onPageSize={setPageSize} />
      </div>
    </>
  );
}
