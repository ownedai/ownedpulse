import { useState } from 'react';
import Logo from '../common/Logo';

const datePresets = [
  { label: 'All', value: null },
  { label: 'Last 30 days', value: '30d' },
  { label: 'Last 90 days', value: '90d' },
  { label: 'Custom', value: 'custom' },
];

export default function FilterBar({ filters, onChange }) {
  const [showCustom, setShowCustom] = useState(false);

  const agencies = ['All', 'FDA', 'EMA', 'ICH'];
  const docTypes = ['All', 'guideline', 'press-release'];
  const docTypeLabels = { All: 'All', guideline: 'Guideline', 'press-release': 'Press Release' };

  const handleAgency = (a) => {
    onChange({ ...filters, agency: a === 'All' ? null : a });
  };

  const handleDocType = (d) => {
    onChange({ ...filters, doc_type: d === 'All' ? null : d });
  };

  const handleDatePreset = (preset) => {
    if (preset === 'custom') {
      setShowCustom(true);
      return;
    }
    setShowCustom(false);
    const now = new Date();
    let date_from = null;
    if (preset === '30d') {
      date_from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    } else if (preset === '90d') {
      date_from = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    }
    onChange({ ...filters, date_from, date_to: null });
  };

  const activeAgency = filters.agency || 'All';
  const activeDocType = filters.doc_type || 'All';

  return (
    <div className="bg-shell-surface border-b border-shell-border px-4 py-2">
      <div className="flex items-center gap-6 text-sm">
        <div className="flex items-center gap-1">
          <span className="text-shell-muted text-xs mr-1">Agency:</span>
          {agencies.map((a) => (
            <button
              key={a}
              onClick={() => handleAgency(a)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                activeAgency === a
                  ? 'bg-accent-dark/15 text-accent-dark border border-accent-dark/30'
                  : 'text-shell-muted hover:text-slate-200 border border-transparent'
              }`}
            >
              {a}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          <span className="text-shell-muted text-xs mr-1">Type:</span>
          {docTypes.map((d) => (
            <button
              key={d}
              onClick={() => handleDocType(d)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                activeDocType === d
                  ? 'bg-accent-dark/15 text-accent-dark border border-accent-dark/30'
                  : 'text-shell-muted hover:text-slate-200 border border-transparent'
              }`}
            >
              {docTypeLabels[d]}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          <span className="text-shell-muted text-xs mr-1">Date:</span>
          {datePresets.map((p) => (
            <button
              key={p.label}
              onClick={() => handleDatePreset(p.value)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                (!filters.date_from && p.value === null && !showCustom) ||
                (filters.date_from && p.value !== null && p.value !== 'custom' && !showCustom)
                  ? 'bg-accent-dark/15 text-accent-dark border border-accent-dark/30'
                  : showCustom && p.value === 'custom'
                    ? 'bg-accent-dark/15 text-accent-dark border border-accent-dark/30'
                    : 'text-shell-muted hover:text-slate-200 border border-transparent'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {showCustom && (
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={filters.date_from || ''}
              onChange={(e) => onChange({ ...filters, date_from: e.target.value || null })}
              className="bg-shell-bg border border-shell-border rounded px-2 py-0.5 text-xs text-slate-200"
            />
            <span className="text-shell-muted text-xs">to</span>
            <input
              type="date"
              value={filters.date_to || ''}
              onChange={(e) => onChange({ ...filters, date_to: e.target.value || null })}
              className="bg-shell-bg border border-shell-border rounded px-2 py-0.5 text-xs text-slate-200"
            />
          </div>
        )}
      </div>
    </div>
  );
}
