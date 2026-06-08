import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { createPortal } from 'react-dom';
import { getCorpusDocumentsV2, deferDocument, resumeDocument } from '../../api/client';
import { formatDate, isFutureDate } from '../../dateFormat';
import Tooltip from '../common/Tooltip';
import { getStatusConfig } from '../../utils/status';
import DateInput, { todayISO } from '../common/DateInput';

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
  { label: 'All corpus', value: null },
  { label: 'Indexed', value: 'indexed' },
  { label: 'Superseded', value: 'superseded' },
  { label: 'Failed', value: 'failed' },
  { label: 'Deferred', value: 'deferred' },
  { label: 'Not viable', value: 'not_viable' },
  { label: 'Processing', value: 'pending' },
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
      <button ref={btnRef} onClick={handleOpen} style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        height: 30, padding: '0 10px',
        background: value != null ? 'var(--accent-tint)' : 'var(--doc-surface)',
        border: `1px solid ${open || value != null ? 'var(--accent-l)' : 'var(--doc-border)'}`,
        borderRadius: 3, cursor: 'pointer',
        color: value != null ? 'var(--accent-l)' : 'var(--doc-text-2)',
        fontSize: 12, fontFamily: 'var(--sans)',
      }}>
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

function isoToEu(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-');
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

function DateRangeFilter({ dateFrom, dateTo, onApply }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(dateFrom || todayISO());
  const [to, setTo] = useState(dateTo || todayISO());
  const ref = useRef(null);
  const active = !!(dateFrom || dateTo);

  useClickOutside(ref, () => setOpen(false));
  useEffect(() => {
    if (open) {
      setFrom(dateFrom || todayISO());
      setTo(dateTo || todayISO());
    }
  }, [open, dateFrom, dateTo]);

  function handleApply() { onApply(from, to); setOpen(false); }
  function handleClear() { onApply('', ''); setOpen(false); }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Filter by publication date"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          height: 30, padding: '0 10px',
          background: active ? 'var(--accent-tint)' : 'var(--doc-surface)',
          border: `1px solid ${active ? 'var(--accent-l)' : 'var(--doc-border)'}`,
          borderRadius: 3, cursor: 'pointer',
          color: active ? 'var(--accent-l)' : 'var(--doc-text-2)', fontSize: 12,
        }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        {active ? `${isoToEu(dateFrom) || '…'} → ${isoToEu(dateTo) || '…'}` : 'Date range'}
      </button>
      {open && (
        <div className="rp-popover" style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, padding: '12px 14px' }}>
          <div className="rp-popover-section-lbl">Publication date</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--doc-text-2)' }}>
              From (dd.mm.yyyy)
              <DateInput value={from} onChange={setFrom} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--doc-text-2)' }}>
              To (dd.mm.yyyy)
              <DateInput value={to} onChange={setTo} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <button className="rp-popover-apply" onClick={handleApply}>Apply</button>
            {(from || to) && (
              <button onClick={handleClear} style={{ height: 30, padding: '0 10px', background: 'transparent', border: '1px solid var(--doc-border)', borderRadius: 4, color: 'var(--doc-text-2)', fontSize: 12, cursor: 'pointer' }}>Clear</button>
            )}
          </div>
        </div>
      )}
    </div>
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
  const [appliedDateFrom, setAppliedDateFrom] = useState('');
  const [appliedDateTo, setAppliedDateTo] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [actionBusy, setActionBusy] = useState(null);

  useEffect(() => {
    const a = searchParams.get('agency');
    const dt = searchParams.get('doc_type');
    setAgency(['FDA', 'EMA', 'ICH'].includes(a) ? a : null);
    setDocType(dt || null);
    setPage(1);
  }, [searchParams]);

  const hasFilters = !!(agency || docType || status || search || appliedDateFrom || appliedDateTo);

  function resetFilters() {
    setAgency(null); setDocType(null); setStatus(null);
    setSearch(''); setAppliedDateFrom(''); setAppliedDateTo('');
    setPage(1);
  }

  const fetchData = useCallback(() => {
    setLoading(true);
    getCorpusDocumentsV2({
      page, page_size: pageSize,
      issuing_body: agency, doc_type: docType, ingestion_status: status,
      date_from: appliedDateFrom || null, date_to: appliedDateTo || null,
    })
      .then((data) => { setItems(data.items || []); setTotal(data.total || 0); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agency, docType, status, appliedDateFrom, appliedDateTo, page, pageSize]);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleDefer(docId) {
    setActionBusy(docId);
    try { await deferDocument(docId); fetchData(); } catch (e) { alert(e.message); }
    finally { setActionBusy(null); }
  }

  async function handleResume(docId) {
    setActionBusy(docId);
    try { await resumeDocument(docId); fetchData(); } catch (e) { alert(e.message); }
    finally { setActionBusy(null); }
  }

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
        <div className="rp-filter-strip" style={{ flexWrap: 'wrap', gap: '6px 8px' }}>
          <input
            type="text"
            placeholder="Search documents…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            style={{
              height: 30, padding: '0 10px', fontSize: 12,
              fontFamily: 'var(--sans)', background: 'var(--doc-surface)',
              border: '1px solid var(--doc-border)', borderRadius: 3,
              color: 'var(--doc-text)', outline: 'none', width: 200,
            }}
          />
          <FilterDropdown options={AGENCY_OPTS} value={agency} onChange={(v) => { setAgency(v); setPage(1); }} />
          <FilterDropdown options={DOC_TYPES} value={docType} onChange={(v) => { setDocType(v); setPage(1); }} />
          <FilterDropdown options={STATUS_OPTS} value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
          <DateRangeFilter
            dateFrom={appliedDateFrom}
            dateTo={appliedDateTo}
            onApply={(from, to) => { setAppliedDateFrom(from); setAppliedDateTo(to); setPage(1); }}
          />
          {hasFilters && (
            <button
              onClick={resetFilters}
              style={{
                display: 'inline-flex', alignItems: 'center',
                height: 30, padding: '0 10px', fontSize: 12,
                fontFamily: 'var(--sans)', background: 'var(--doc-surface)',
                border: '1px solid var(--doc-border)', borderRadius: 3,
                color: 'var(--doc-text-2)', cursor: 'pointer',
              }}
            >
              Reset
            </button>
          )}
        </div>

        <table className="rp-table" style={{ fontSize: 12.5, tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th>Document</th>
              <th style={{ width: 55 }}>Agency</th>
              <th style={{ width: 110 }}>Type</th>
              <th style={{ width: 70 }}>Version</th>
              <th style={{ width: 95 }}>Published</th>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 55, textAlign: 'right' }}>Chunks</th>
              <th style={{ width: 70 }}></th>
            </tr>
          </thead>
          <tbody>
            {loading && filteredItems.length === 0 && (
              <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 12 }}>Loading…</td></tr>
            )}
            {!loading && filteredItems.length === 0 && (
              <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)', fontFamily: 'var(--mono)', fontSize: 12 }}>No documents found.</td></tr>
            )}
            {filteredItems.map((doc) => (
              <tr key={doc.document_id}>
                <td style={{ maxWidth: 0 }}>
                  <Link
                    to={`/corpus/${encodeURIComponent(doc.document_id)}`}
                    title={doc.document_title || doc.document_id}
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
                <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
                  {isFutureDate(doc.publication_date) ? (
                    <Tooltip tip="Future effective date — this document is not yet in force">
                      <span style={{ cursor: 'help', borderBottom: '1px dashed currentColor' }}>{formatDate(doc.publication_date)}</span>
                    </Tooltip>
                  ) : formatDate(doc.publication_date)}
                </td>
                <td><StatusBadge status={doc.ingestion_status} /></td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.chunk_count || '—'}</td>
                <td style={{ textAlign: 'right' }}>
                  {doc.ingestion_status === 'failed' && (
                    <button
                      disabled={actionBusy === doc.document_id}
                      onClick={(e) => { e.preventDefault(); handleDefer(doc.document_id); }}
                      style={{
                        fontSize: 11, fontFamily: 'var(--mono)', padding: '2px 8px',
                        borderRadius: 3, cursor: 'pointer', border: '1px solid var(--doc-border)',
                        background: 'transparent', color: 'var(--doc-text-2)',
                        opacity: actionBusy === doc.document_id ? 0.5 : 1,
                      }}
                    >
                      Defer
                    </button>
                  )}
                  {doc.ingestion_status === 'deferred' && (
                    <button
                      disabled={actionBusy === doc.document_id}
                      onClick={(e) => { e.preventDefault(); handleResume(doc.document_id); }}
                      style={{
                        fontSize: 11, fontFamily: 'var(--mono)', padding: '2px 8px',
                        borderRadius: 3, cursor: 'pointer', border: '1px solid var(--accent-l)',
                        background: 'transparent', color: 'var(--accent-l)',
                        opacity: actionBusy === doc.document_id ? 0.5 : 1,
                      }}
                    >
                      Resume
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <Pager page={page} pageSize={pageSize} total={search ? filteredItems.length : total} onPage={setPage} onPageSize={setPageSize} />
      </div>
    </>
  );
}
