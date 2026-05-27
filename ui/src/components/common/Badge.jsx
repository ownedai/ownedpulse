const variants = {
  agency: {
    FDA: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    EMA: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    ICH: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  },
  superseded: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  doc_type: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
};

export default function Badge({ type = 'doc_type', value, className = '' }) {
  if (!value) return null;
  let style = variants.doc_type;
  if (type === 'agency' && variants.agency[value]) {
    style = variants.agency[value];
  } else if (type === 'superseded') {
    style = variants.superseded;
  }

  return (
    <span className={`inline-block text-[11px] font-medium px-2 py-0.5 rounded border ${style} ${className}`}>
      {value}
    </span>
  );
}
