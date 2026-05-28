import { useState, useCallback } from 'react';
import { Routes, Route, useSearchParams } from 'react-router-dom';
import TopNav from './components/layout/TopNav';
import Sidebar from './components/layout/Sidebar';
import FilterBar from './components/layout/FilterBar';
import RetrievalSettings from './components/layout/RetrievalSettings';
import EmptyState from './components/query/EmptyState';
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

  const retrievalDisplay = (r) => ({
    depth: r.depth,
    k: r.topK,
    score: r.scoreThreshold,
  });

  const handleSubmit = useCallback((text) => {
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
      <div className="rp-content">
        <div className="rp-content-inner">
          <div style={{ maxWidth: 760, margin: '0 auto' }}>
            {loading && (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--doc-text-2)' }}>
                <p>Searching across regulatory documents...</p>
              </div>
            )}
            {error && (
              <div style={{ padding: 24, background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)' }}>
                {error}
              </div>
            )}
            {result && (
              <div>
                <div style={{ fontSize: 13, color: 'var(--doc-text-2)', marginBottom: 8 }}>
                  Query: {queryText}
                </div>
                <div style={{
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'var(--sans)',
                  fontSize: 16,
                  lineHeight: 1.75,
                  color: 'var(--doc-text)',
                }}>
                  {result.answer}
                </div>
                {result.citations && result.citations.length > 0 && (
                  <div style={{ marginTop: 32 }}>
                    <div style={{
                      fontFamily: 'var(--mono)',
                      fontSize: 11,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      color: 'var(--doc-text-2)',
                      marginBottom: 12,
                    }}>
                      Sources ({result.citations.length})
                    </div>
                    {result.citations.map((c) => (
                      <div key={c.index} style={{
                        padding: 12,
                        marginBottom: 8,
                        background: 'var(--doc-surface)',
                        border: '1px solid var(--doc-border)',
                        borderRadius: 4,
                        fontSize: 13,
                      }}>
                        <div style={{ fontWeight: 500, marginBottom: 4 }}>
                          [{c.index}] {c.document_title}
                        </div>
                        <div style={{ color: 'var(--doc-text-2)', fontSize: 12 }}>
                          {c.issuing_body} &middot; Score: {c.score?.toFixed(2)}
                          {c.cited_by_llm ? ' · Cited' : ' · Not cited'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {result.query_id && (
                  <div style={{
                    marginTop: 24,
                    paddingTop: 16,
                    borderTop: '1px solid var(--doc-border)',
                    fontFamily: 'var(--mono)',
                    fontSize: 11,
                    color: 'var(--doc-text-3)',
                  }}>
                    Query ID: {result.query_id} &middot; {new Date(result.timestamp).toLocaleDateString('en-GB')} {new Date(result.timestamp).toLocaleTimeString('en-GB')} &middot; {result.routing_path}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
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
