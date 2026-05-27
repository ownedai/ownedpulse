export default function QueryInput({ value, onChange, onSubmit, loading }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && value.trim() && !loading) {
      e.preventDefault();
      onSubmit(value.trim());
    }
  };

  return (
    <div className="mb-6">
      <div className="flex gap-3">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a regulatory question..."
          disabled={loading}
          className="flex-1 bg-white border border-slate-300 rounded-lg px-4 py-2.5 text-[15px] text-primary placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-accent-light/20 focus:border-accent-light transition-shadow disabled:opacity-60"
        />
        <button
          onClick={() => value.trim() && onSubmit(value.trim())}
          disabled={!value.trim() || loading}
          className="px-5 py-2.5 bg-accent-light text-white rounded-lg font-medium text-sm hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Submit
        </button>
      </div>
    </div>
  );
}
