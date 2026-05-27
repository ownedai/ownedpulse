import { useState, useCallback } from 'react';
import Sidebar from './components/layout/Sidebar';
import FilterBar from './components/layout/FilterBar';
import SourcePanel from './components/layout/SourcePanel';
import EmptyState from './components/query/EmptyState';
import QueryInput from './components/query/QueryInput';
import AnswerPanel from './components/query/AnswerPanel';
import ThinkingIndicator from './components/query/ThinkingIndicator';
import { useQuery } from './hooks/useQuery';
import { useHistory } from './hooks/useHistory';
import { useCorpusStats } from './hooks/useCorpusStats';

export default function App() {
  const [filters, setFilters] = useState({ agency: null, doc_type: null, date_from: null, date_to: null });
  const [queryText, setQueryText] = useState('');
  const { result, loading, error, submitQuery, clearResult } = useQuery();
  const { history, refresh: refreshHistory } = useHistory();
  const { stats } = useCorpusStats();
  const [sourcePanel, setSourcePanel] = useState(null);
  const [highlightedCitation, setHighlightedCitation] = useState(null);

  const handleSubmit = (text) => {
    setQueryText(text);
    setHighlightedCitation(null);
    setSourcePanel(null);
    submitQuery(text, filters);
    setTimeout(refreshHistory, 500);
  };

  const handleHistorySelect = (item) => {
    setQueryText(item.query_text);
    setHighlightedCitation(null);
    setSourcePanel(null);
    clearResult();
  };

  const handleCitationClick = useCallback((index) => {
    setHighlightedCitation(prev => prev === index ? null : index);
  }, []);

  const handleViewSource = (citation) => {
    setSourcePanel(citation);
  };

  return (
    <div className="flex h-full">
      <Sidebar
        history={history}
        stats={stats}
        onHistorySelect={handleHistorySelect}
        onNewQuery={() => { clearResult(); setQueryText(''); setHighlightedCitation(null); setSourcePanel(null); }}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <FilterBar filters={filters} onChange={setFilters} />
        <div className="flex flex-1 min-h-0">
          <main
            className={`flex-1 bg-panel-bg overflow-y-auto transition-all ${
              sourcePanel ? 'w-[60%]' : 'w-full'
            }`}
          >
            <div className="max-w-3xl mx-auto px-8 py-8">
              {!result && !loading && !error && !queryText && (
                <EmptyState onChipClick={(t) => handleSubmit(t)} />
              )}

              <QueryInput
                value={queryText}
                onChange={setQueryText}
                onSubmit={handleSubmit}
                loading={loading}
              />

              {loading && <ThinkingIndicator />}

              {error && (
                <div className="bg-red-50 border border-error/20 rounded-lg p-4 text-error text-sm">
                  {error}
                </div>
              )}

              {result && (
                <AnswerPanel
                  result={result}
                  highlightedCitation={highlightedCitation}
                  onCitationClick={handleCitationClick}
                  onViewSource={handleViewSource}
                />
              )}
            </div>
          </main>

          {sourcePanel && (
            <SourcePanel
              citation={sourcePanel}
              onClose={() => setSourcePanel(null)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
