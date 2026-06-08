import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { getQueryHistory, exportHistory, getAuditCount } from '../../api/client';
import { formatDateTime, todayISO } from '../../dateFormat';

function useClickOutside(ref, handler) {
  useEffect(() => {
    function onDown(e) {
      if (!ref.current || ref.current.contains(e.target)) return;
      // Don't close if a date input inside the ref has focus (native calendar is open)
      if (ref.current.querySelector('input[type="date"]:focus')) return;
      handler();
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [ref, handler]);
}

const ROUTING_OPTS = [
  { label: 'All routing', value: null },
  { label: 'Semantic', value: 'CONTENT' },
  { label: 'Metadata', value: 'METADATA' },
];

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
            <div key={o.label} className={`rp-popover-item${value === o.value ? ' active' : ''}`}
              onClick={() => { onChange(o.value); setOpen(false); }}>
              {o.label}
            </div>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}

function DateRangeFilter({ dateFrom, dateTo, onApply }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(dateFrom);
  const [to, setTo] = useState(dateTo);
  const ref = useRef(null);
  const active = !!(dateFrom || dateTo);

  useClickOutside(ref, () => setOpen(false));
  useEffect(() => { setFrom(dateFrom); setTo(dateTo); }, [dateFrom, dateTo]);

  function handleApply() { onApply(from, to); setOpen(false); }
  function handleClear() { setFrom(''); setTo(''); onApply('', ''); setOpen(false); }

  const inputStyle = {
    background: 'var(--doc-bg)', border: '1px solid var(--doc-border)',
    borderRadius: 4, padding: '5px 8px', fontFamily: 'var(--mono)',
    fontSize: 12, color: 'var(--doc-text)', outline: 'none',
  };

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Filter by query date"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          height: 30, padding: '0 10px',
          background: active ? 'var(--accent-tint)' : 'var(--doc-surface)',
          border: `1px solid ${active ? 'var(--accent-l)' : 'var(--doc-border)'}`,
          borderRadius: 3, cursor: 'pointer',
          color: active ? 'var(--accent-l)' : 'var(--doc-text-2)', fontSize: 12,
          fontFamily: 'var(--sans)',
        }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        {active ? `${dateFrom || '…'} → ${dateTo || '…'}` : 'Date range'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0,
          background: 'var(--doc-surface)', border: '1px solid var(--doc-border)',
          borderRadius: 6, zIndex: 100, padding: '14px 16px',
          boxShadow: '0 4px 16px rgba(0,0,0,0.18)', minWidth: 230,
        }}>
          <div style={{ fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--doc-text-3)', fontWeight: 600, marginBottom: 12 }}>Query date</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--doc-text-2)' }}>
              From
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--doc-text-2)' }}>
              To
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} style={inputStyle} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
            <button onClick={handleApply} style={{ flex: 1, height: 28, background: 'var(--accent-d)', color: '#fff', border: 'none', borderRadius: 4, fontSize: 12, cursor: 'pointer', fontFamily: 'var(--sans)' }}>Apply</button>
            {active && <button onClick={handleClear} style={{ height: 28, padding: '0 10px', background: 'transparent', color: 'var(--doc-text-2)', border: '1px solid var(--doc-border)', borderRadius: 4, fontSize: 12, cursor: 'pointer', fontFamily: 'var(--sans)' }}>Clear</button>}
          </div>
        </div>
      )}
    </div>
  );
}

function Pager({ page, pageSize, total, onPage, onPageSize }) {
  const totalPages = Math.ceil(total / pageSize);
  if (total === 0) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

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
            <button key={n} onClick={() => { onPageSize(n); onPage(1); }} style={{
              background: pageSize === n ? 'var(--accent-l)' : 'var(--doc-surface)',
              border: 'none', borderRight: '1px solid var(--doc-border)',
              color: pageSize === n ? '#fff' : 'var(--doc-text-2)',
              fontFamily: 'var(--mono)', fontSize: 11,
              padding: '3px 9px', cursor: 'pointer',
            }}>{n}</button>
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

export default function HistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState({ field: 'timestamp', dir: 'desc' });
  const [search, setSearch] = useState('');
  const [routingPath, setRoutingPath] = useState(null);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [exportFormat, setExportFormat] = useState('csv');
  const [isExporting, setIsExporting] = useState(false);

  const hasFilters = !!(search || routingPath || dateFrom || dateTo);

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [search, routingPath, dateFrom, dateTo, pageSize]);

  const fetchData = useCallback(() => {
    setLoading(true);
    const offset = (page - 1) * pageSize;
    getQueryHistory(pageSize, offset, { search, routingPath, dateFrom, dateTo })
      .then((data) => { setItems(data.items ?? data); setTotal(data.total ?? (data.items ?? data).length); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page, pageSize, search, routingPath, dateFrom, dateTo]);

  useEffect(() => { fetchData(); }, [fetchData]);

  function handleExport() {
    setIsExporting(true);
    exportHistory({ format: exportFormat, dateFrom, dateTo, search, routingPath: routingPath || '' })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `regpulse-audit-${todayISO()}.${exportFormat}`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((err) => alert(`Export failed: ${err.message}`))
      .finally(() => setIsExporting(false));
  }

  function resetFilters() {
    setSearch('');
    setRoutingPath(null);
    setDateFrom('');
    setDateTo('');
  }

  let filtered = [...items].sort((a, b) => {
    const aVal = a[sort.field] || '';
    const bVal = b[sort.field] || '';
    const cmp = String(aVal).localeCompare(String(bVal));
    return sort.dir === 'asc' ? cmp : -cmp;
  });

  function handleSort(field) {
    setSort((prev) => ({
      field,
      dir: prev.field === field && prev.dir === 'desc' ? 'asc' : 'desc',
    }));
  }

  function sortClass(field) {
    if (sort.field !== field) return 'sortable';
    return `sortable sorted-${sort.dir}`;
  }

  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Query history</h1>
          <p>Every query executed on this instance, recorded for compliance traceability.</p>
        </div>
      </div>

      <div className="rp-table-wrap">
        <div className="rp-filter-strip" style={{ flexWrap: 'wrap', gap: '6px 8px' }}>
          <input
            type="text"
            placeholder="Search queries…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              height: 30, padding: '0 10px', fontSize: 12,
              fontFamily: 'var(--sans)', background: 'var(--doc-surface)',
              border: '1px solid var(--doc-border)', borderRadius: 3,
              color: 'var(--doc-text)', outline: 'none', width: 220,
            }}
          />
          <FilterDropdown options={ROUTING_OPTS} value={routingPath} onChange={setRoutingPath} />
          <DateRangeFilter dateFrom={dateFrom} dateTo={dateTo} onApply={(f, t) => { setDateFrom(f); setDateTo(t); }} />
          {hasFilters && (
            <button onClick={resetFilters} style={{
              display: 'inline-flex', alignItems: 'center',
              height: 30, padding: '0 10px', fontSize: 12,
              fontFamily: 'var(--sans)', background: 'var(--doc-surface)',
              border: '1px solid var(--doc-border)', borderRadius: 3,
              color: 'var(--doc-text-2)', cursor: 'pointer',
            }}>Reset</button>
          )}
          <div style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)', alignSelf: 'center' }}>
            {total} records
          </span>
          <select
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value)}
            style={{
              height: 30, padding: '0 8px', fontSize: 12,
              fontFamily: 'var(--sans)', background: 'var(--doc-surface)',
              border: '1px solid var(--doc-border)', borderRadius: 3,
              color: 'var(--doc-text)', cursor: 'pointer',
            }}
          >
            <option value="csv">CSV</option>
            <option value="pdf">PDF</option>
          </select>
          <button className="rp-export" onClick={handleExport} disabled={isExporting}>
            {isExporting ? 'Exporting…' : 'Export audit log'}
          </button>
        </div>

        <table className="rp-table">
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th>Query</th>
              <th className={sortClass('timestamp')} onClick={() => handleSort('timestamp')}>Date/Time</th>
              <th className={sortClass('agency_filter')} onClick={() => handleSort('agency_filter')}>Agency</th>
              <th className={sortClass('citation_count')} onClick={() => handleSort('citation_count')}>Sources</th>
              <th style={{ width: 80 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && filtered.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>
                  Loading…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>
                  No queries found.
                </td>
              </tr>
            )}
            {filtered.map((h, i) => (
              <tr key={h.query_id}>
                <td className="num">{(page - 1) * pageSize + i + 1}</td>
                <td>
                  <span className="truncate" title={h.query_text}>{h.query_text}</span>
                  <span className="query-sub">
                    <span className="query-id">{h.query_id}</span>
                    {h.routing_path === 'METADATA' && (
                      <span className="rp-meta-badge" title="Metadata lookup">Metadata lookup</span>
                    )}
                  </span>
                </td>
                <td className="mono">{formatDateTime(h.timestamp)}</td>
                <td>
                  <span className="agency-mini">{h.agency_filter || h.filters_applied?.agency || 'All'}</span>
                </td>
                <td className="mono">{h.citation_count ?? '—'}</td>
                <td>
                  <button
                    className="action primary"
                    onClick={() => navigate(`/?q=${h.query_id}`)}
                  >
                    Load
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <Pager page={page} pageSize={pageSize} total={total} onPage={setPage} onPageSize={setPageSize} />
      </div>
    </>
  );
}
