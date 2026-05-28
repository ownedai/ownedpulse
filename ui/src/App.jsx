import { useState, useCallback, useMemo } from 'react';
import { Routes, Route, useSearchParams } from 'react-router-dom';
import TopNav from './components/layout/TopNav';
import Sidebar from './components/layout/Sidebar';
import FilterBar from './components/layout/FilterBar';
import RetrievalSettings from './components/layout/RetrievalSettings';
import SourcePanel from './components/layout/SourcePanel';
import EmptyState from './components/query/EmptyState';
import AnswerPanel from './components/query/AnswerPanel';
import CitationCard from './components/query/CitationCard';
import QueryExpansion from './components/query/QueryExpansion';
import AuditFooter from './components/query/AuditFooter';
import useQuery from './hooks/useQuery';

function MainPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { result, loading, error, queryText, execute, clear } = useQuery();

  const [filters, setFilters] = useState({});
  const [retrieval, setRetrieval] = useState({
    depth: 'standard',
    topK: 10,
    scoreThreshold: 0.60,
  });
  const [retrievalOpen, setRetrievalOpen] = useState(false);
  const [activeCitation, setActiveCitation] = useState(null);

  const retrievalDisplay = (r) => ({
    depth: r.depth,
    k: r.topK,
    score: r.scoreThreshold,
  });

  const handleSubmit = useCallback((text) => {
    setActiveCitation(null);
    execute(text, filters, {
      query_depth: retrieval.depth,
      top_k: retrieval.topK,
      score_threshold: retrieval.scoreThreshold,
    });
  }, [execute, filters, retrieval]);

  const handleNewQuery = useCallback(() => {
    clear();
    setSearchParams({});
  }, [clear, setSearchParams]);

  // Find active citation object
  const activeCitationObj = useMemo(() => {
    if (activeCitation == null || !result?.citations) return null;
    return result.citations.find((c) => c.index === activeCitation) || null;
  }, [activeCitation, result?.citations]);

  // Find citations in same document for chunk navigation
  const sameDocCitations = useMemo(() => {
    if (!activeCitationObj || !result?.citations) return [];
    return result.citations.filter((c) => c.document_id === activeCitationObj.document_id);
  }, [activeCitationObj, result?.citations]);

  const handlePrevChunk = useCallback(() => {
    if (sameDocCitations.length < 2) return;
    const currentIdx = sameDocCitations.findIndex((c) => c.index === activeCitation);
    if (currentIdx > 0) {
      setActiveCitation(sameDocCitations[currentIdx - 1].index);
    }
  }, [sameDocCitations, activeCitation]);

  const handleNextChunk = useCallback(() => {
    if (sameDocCitations.length < 2) return;
    const currentIdx = sameDocCitations.findIndex((c) => c.index === activeCitation);
    if (currentIdx < sameDocCitations.length - 1) {
      setActiveCitation(sameDocCitations[currentIdx + 1].index);
    }
  }, [sameDocCitations, activeCitation]);

  const hasPrev = sameDocCitations.length > 1 && sameDocCitations.findIndex((c) => c.index === activeCitation) > 0;
  const hasNext = sameDocCitations.length > 1 && sameDocCitations.findIndex((c) => c.index === activeCitation) < sameDocCitations.length - 1;

  // Show landing page when no query has been submitted
  if (!result && !loading && !error) {
    return (
      <>
        <FilterBar
          filters={filters}
          onChange={setFilters}
          retrievalOpen={retrievalOpen}
          onToggleRetrieval={() => setRetrievalOpen((v) => !v)}
          retrieval={retrievalDisplay(retrieval)}
        />
        {retrievalOpen && (
          <RetrievalSettings
            depth={retrieval.depth}
            topK={retrieval.topK}
            scoreThreshold={retrieval.scoreThreshold}
            onChange={(v) => setRetrieval((prev) => ({ ...prev, ...v }))}
          />
        )}
        <EmptyState onSubmit={handleSubmit} disabled={loading} filters={filters} />
      </>
    );
  }

  // Active query — result, loading, or error state
  return (
    <>
      <FilterBar
        filters={filters}
        onChange={setFilters}
        retrievalOpen={retrievalOpen}
        onToggleRetrieval={() => setRetrievalOpen((v) => !v)}
        retrieval={retrievalDisplay(retrieval)}
      />
      {retrievalOpen && (
        <RetrievalSettings
          depth={retrieval.depth}
          topK={retrieval.topK}
          scoreThreshold={retrieval.scoreThreshold}
          onChange={(v) => setRetrieval((prev) => ({ ...prev, ...v }))}
        />
      )}
      <div className="rp-content-wrap">
        <div className={`rp-content${activeCitationObj ? ' with-source' : ''}`}>
          <div className="rp-content-inner">
            <div className="container">
              {/* Query bar */}
              <div className={`rp-query-bar${loading ? ' thinking' : ''}`}>
                <div className="q-row">
                  <div className="q-text">{queryText}</div>
                  <button
                    className="submit"
                    onClick={() => handleSubmit(queryText)}
                    disabled={loading}
                  >
                    Submit
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 8h10M9 4l4 4-4 4" />
                    </svg>
                  </button>
                </div>
                {loading && (
                  <>
                    <div className="rp-thinking-bar" />
                    <div className="rp-thinking-meta">
                      Searching {result?.retrieval_params_applied?.sub_query_count || retrieval.topK} variations across indexed documents...
                    </div>
                  </>
                )}
              </div>

              {/* Error state */}
              {error && (
                <div style={{ padding: 24, background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)' }}>
                  {error}
                </div>
              )}

              {/* Result */}
              {result && (
                <>
                  <AnswerPanel
                    answer={result.answer}
                    activeCitation={activeCitation}
                    onCitationClick={(n) => setActiveCitation(n === activeCitation ? null : n)}
                  />

                  <QueryExpansion subQueries={result.sub_queries} />

                  {/* Sources section */}
                  {result.citations && result.citations.length > 0 && (
                    <>
                      <div className="rp-sources-head">
                        <div className="rp-sources-lbl">
                          Sources <span className="count">({result.citations.length})</span>
                        </div>
                        <button className="rp-export" onClick={() => {}}>
                          Export
                          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M8 3v8M4 7l4 4 4-4M3 13h10" />
                          </svg>
                        </button>
                      </div>
                      <div className="rp-cit-list">
                        {result.citations.map((c) => (
                          <CitationCard
                            key={c.index}
                            citation={c}
                            isActive={activeCitation === c.index}
                            onClick={() => setActiveCitation(c.index === activeCitation ? null : c.index)}
                            onViewSource={() => setActiveCitation(c.index)}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {/* No sources message */}
                  {(!result.citations || result.citations.length === 0) && result.answer && (
                    <div style={{
                      marginTop: 24,
                      padding: 16,
                      background: 'var(--doc-bg)',
                      border: '1px solid var(--doc-border)',
                      borderRadius: 4,
                      fontFamily: 'var(--mono)',
                      fontSize: 12,
                      color: 'var(--doc-text-2)',
                      textAlign: 'center',
                    }}>
                      No sources above the relevance threshold were found for this query.
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <AuditFooter
            queryId={result?.query_id}
            timestamp={result?.timestamp}
            routingPath={result?.routing_path}
            onViewTrace={() => {}}
          />
        </div>

        {activeCitationObj && (
          <SourcePanel
            citation={activeCitationObj}
            onClose={() => setActiveCitation(null)}
            onPrevChunk={handlePrevChunk}
            onNextChunk={handleNextChunk}
            hasPrev={hasPrev}
            hasNext={hasNext}
          />
        )}
      </div>
    </>
  );
}

export default function App() {
  const [resetKey, setResetKey] = useState(0);

  return (
    <div className="app-shell">
      <Sidebar onNewQuery={() => setResetKey((k) => k + 1)} />
      <div className="main-column">
        <TopNav />
        <Routes>
          <Route path="/" element={<MainPage key={resetKey} />} />
        </Routes>
      </div>
    </div>
  );
}
