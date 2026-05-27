import { useCallback } from 'react';
import CitationCard from './CitationCard';

export default function AnswerPanel({ result, highlightedCitation, onCitationClick, onViewSource }) {

  const handleAnswerClick = useCallback((e) => {
    const cite = e.target.closest('[data-cite]');
    if (cite) {
      const idx = parseInt(cite.getAttribute('data-cite'), 10);
      if (idx > 0) onCitationClick(idx);
    }
  }, [onCitationClick]);

  const handleExport = async () => {
    try {
      const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001';
      const res = await fetch(`${API_BASE}/api/query/${result.query_id}/export`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `regpulse-export-${result.query_id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Export failed', e);
    }
  };

  return (
    <div>
      <div className="answer-prose mb-8" onClick={handleAnswerClick}>
        {result.routing_path === 'CONTENT' ? (
          <div dangerouslySetInnerHTML={{ __html: result.answer }}
            className="[&_ol]:my-2 [&_li]:mb-1 [&_p]:mb-3 [&_p:last-child]:mb-0"
          />
        ) : (
          <div dangerouslySetInnerHTML={{ __html: result.answer }} />
        )}
      </div>

      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-700">
          Citations ({result.citations?.length || 0})
        </h3>
        <button
          onClick={handleExport}
          className="text-xs font-medium text-accent-light hover:text-accent-hover flex items-center gap-1"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 1.5V9.5M7 9.5L3.5 6M7 9.5L10.5 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1.5 10V11.5C1.5 12.052 1.948 12.5 2.5 12.5H11.5C12.052 12.5 12.5 12.052 12.5 11.5V10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Export session
        </button>
      </div>

      <div className="space-y-3">
        {result.citations?.map((c) => (
          <CitationCard
            key={c.index}
            citation={c}
            highlighted={highlightedCitation === c.index}
            onClick={() => onCitationClick(c.index)}
            onViewSource={() => onViewSource(c)}
          />
        ))}
      </div>

      <div className="mt-8 pt-4 border-t border-slate-200 text-xs text-secondary">
        Query ID: {result.query_id} · {new Date(result.timestamp).toLocaleString()} · {result.routing_path}
      </div>
    </div>
  );
}
