export default function ProvMetadata({ citation }) {
  if (!citation) return null;

  const rows = [
    ['Source file', citation.local_file_path || 'Not available'],
    ['Document version', citation.document_version || '—'],
    ['Clause ID', citation.clause_id || '—'],
    ['Publication date', citation.publication_date || '—'],
    ['Agency', citation.agency],
    ['Source URL', citation.source_url],
  ];

  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
        Provenance Metadata
      </h4>
      <table className="w-full text-xs">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-b border-slate-100 last:border-0">
              <td className="py-1.5 pr-3 text-slate-500 font-medium w-[120px]">{label}</td>
              <td className="py-1.5 text-slate-800 break-all">
                {value && String(value).startsWith('http') ? (
                  <a href={value} target="_blank" rel="noopener noreferrer" className="text-accent-light hover:underline">
                    {value}
                  </a>
                ) : (
                  value
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
