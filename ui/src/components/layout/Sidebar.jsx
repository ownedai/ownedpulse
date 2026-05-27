import Logo from '../common/Logo';

export default function Sidebar({ history, stats, onHistorySelect, onNewQuery }) {
  return (
    <aside className="w-[240px] min-w-[240px] bg-shell-bg flex flex-col h-full border-r border-shell-border">
      <div className="px-4 py-4 border-b border-shell-border">
        <Logo />
      </div>

      <div className="px-3 py-3">
        <button
          onClick={onNewQuery}
          className="w-full py-2 bg-accent-dark text-white rounded-lg font-medium text-sm hover:bg-[#4B8FE0] transition-colors"
        >
          New query
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-1">
        <h3 className="text-[10px] font-semibold text-shell-muted uppercase tracking-wider px-1 mb-2">
          Query History
        </h3>
        {history.length === 0 ? (
          <p className="text-xs text-shell-muted px-1">No queries yet.</p>
        ) : (
          <div className="space-y-0.5">
            {history.map((item) => (
              <button
                key={item.query_id}
                onClick={() => onHistorySelect(item)}
                className="w-full text-left px-2.5 py-2 rounded-md hover:bg-shell-surface transition-colors group"
              >
                <p className="text-xs text-slate-300 truncate">{item.query_text}</p>
                <p className="text-[10px] text-shell-muted mt-0.5">
                  {item.timestamp ? new Date(item.timestamp).toLocaleDateString() : ''}
                  {item.routing_path && ` · ${item.routing_path}`}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="px-3 py-3 border-t border-shell-border">
        <h3 className="text-[10px] font-semibold text-shell-muted uppercase tracking-wider mb-2">
          Corpus
        </h3>
        {stats ? (
          <div className="space-y-1 text-xs text-slate-400">
            <div className="flex justify-between">
              <span>Documents</span>
              <span className="text-slate-200 font-medium">{stats.total_documents || 0}</span>
            </div>
            {stats.per_agency && Object.entries(stats.per_agency).map(([agency, count]) => (
              <div key={agency} className="flex justify-between">
                <span>{agency}</span>
                <span className="text-slate-200 font-medium">{count}</span>
              </div>
            ))}
            {stats.last_pipeline_run && (
              <div className="pt-1 text-[10px] text-shell-muted">
                Last pipeline: {new Date(stats.last_pipeline_run).toLocaleDateString()}
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-shell-muted">Connecting...</p>
        )}
      </div>
    </aside>
  );
}
