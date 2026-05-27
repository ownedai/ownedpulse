const examples = [
  'What are the Annex 11 requirements for audit trails?',
  'Summarise ICH Q9(R1) changes from the 2005 version.',
  'What FDA guidance applies to computerised system validation?',
];

export default function EmptyState({ onChipClick }) {
  return (
    <div className="mb-10 mt-8 text-center">
      <h2 className="text-xl font-semibold text-slate-800 mb-6">
        Query regulatory intelligence
      </h2>
      <div className="flex flex-wrap justify-center gap-2.5">
        {examples.map((text) => (
          <button
            key={text}
            onClick={() => onChipClick(text)}
            className="px-4 py-2 bg-white border border-slate-200 rounded-full text-sm text-slate-600 hover:border-accent-light hover:text-accent-light transition-colors shadow-sm"
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
