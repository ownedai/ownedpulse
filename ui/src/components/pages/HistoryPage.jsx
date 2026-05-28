import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getQueryHistory, exportHistory } from '../../api/client';
import { formatDateTime, todayISO } from '../../dateFormat';

export default function HistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState({ field: 'timestamp', dir: 'desc' });
  const [filterAgency, setFilterAgency] = useState('All');
  const [filterRouting, setFilterRouting] = useState('All');
  const limit = 50;

  const fetchData = useCallback(() => {
    setLoading(true);
    getQueryHistory(limit, offset)
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [offset]);

  useEffect(() => { fetchData(); }, [fetchData]);

  function handleExport(format) {
    exportHistory(format)
      .then((data) => {
        if (format === 'json') {
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `regpulse-history-export-${todayISO()}.json`;
          a.click();
          URL.revokeObjectURL(url);
        } else {
          // CSV comes as text
          const blob = new Blob([data], { type: 'text/csv' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `regpulse-history-export-${todayISO()}.csv`;
          a.click();
          URL.revokeObjectURL(url);
        }
      })
      .catch(() => {});
  }

  // Apply client-side filtering
  let filtered = items;
  if (filterAgency !== 'All') {
    filtered = filtered.filter((h) => h.agency_filter === filterAgency || (h.filters_applied?.agency === filterAgency));
  }
  if (filterRouting !== 'All') {
    filtered = filtered.filter((h) => h.routing_path === filterRouting);
  }

  // Sort
  filtered = [...filtered].sort((a, b) => {
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
        <div className="actions">
          <button className="rp-export" onClick={() => handleExport('json')}>Export JSON</button>
          <button className="rp-export" onClick={() => handleExport('csv')}>Export CSV</button>
        </div>
      </div>

      <div className="rp-table-wrap">
        <div className="rp-filter-strip">
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>Filter:</span>
          <select value={filterAgency} onChange={(e) => setFilterAgency(e.target.value)} className="select">
            <option value="All">All agencies</option>
            <option value="FDA">FDA</option>
            <option value="EMA">EMA</option>
            <option value="ICH">ICH</option>
          </select>
          <select value={filterRouting} onChange={(e) => setFilterRouting(e.target.value)} className="select">
            <option value="All">All routing</option>
            <option value="CONTENT">Semantic search</option>
            <option value="METADATA">Metadata lookup</option>
          </select>
          <div className="spacer" style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
            {filtered.length} records
          </span>
        </div>

        <table className="rp-table">
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th>Query</th>
              <th className={sortClass('timestamp')} onClick={() => handleSort('timestamp')}>Date/Time</th>
              <th className={sortClass('routing_path')} onClick={() => handleSort('routing_path')}>Routing</th>
              <th className={sortClass('agency_filter')} onClick={() => handleSort('agency_filter')}>Agency</th>
              <th className={sortClass('citation_count')} onClick={() => handleSort('citation_count')}>Sources</th>
              <th style={{ width: 80 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>
                  Loading...
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)' }}>
                  No queries found.
                </td>
              </tr>
            )}
            {filtered.map((h, i) => (
              <tr key={h.query_id}>
                <td className="num">{offset + i + 1}</td>
                <td>
                  <span className="truncate" title={h.query_text}>{h.query_text}</span>
                </td>
                <td className="mono">{formatDateTime(h.timestamp)}</td>
                <td>
                  <span className="routing">
                    {h.routing_path === 'METADATA' ? 'Metadata' : 'Semantic'}
                  </span>
                </td>
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

        <div className="rp-pager">
          <span>{offset + 1}–{Math.min(offset + limit, offset + items.length)} of many</span>
          <div className="pages">
            <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}>
              &larr;
            </button>
            <button onClick={() => setOffset(offset + limit)}>
              &rarr;
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
