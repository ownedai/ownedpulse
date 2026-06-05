import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Routes, Route, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import TopNav from './components/layout/TopNav';
import Sidebar from './components/layout/Sidebar';
import FilterBar from './components/layout/FilterBar';
import SourcePanel from './components/layout/SourcePanel';
import EmptyState from './components/query/EmptyState';
import QueryInput from './components/query/QueryInput';
import AnswerPanel from './components/query/AnswerPanel';
import CitationCard from './components/query/CitationCard';
import QueryExpansion from './components/query/QueryExpansion';
import AuditFooter from './components/query/AuditFooter';
import HistoryPage from './components/pages/HistoryPage';
import CorpusPage from './components/pages/CorpusPage';
import DocumentDetailPage from './components/pages/DocumentDetailPage';
import RunLogPage from './components/pages/RunLogPage';
import IngestionsPage from './components/pages/IngestionsPage';
import QueryPage from './components/pages/QueryPage';
import SourcesPage from './components/pages/SourcesPage';
import useQuery from './hooks/useQuery';
import useModelStatus from './hooks/useModelStatus';
import { ModelStatusContext } from './context/ModelStatusContext';
import { exportQuery, getBootstrapState } from './api/client';
import CorpusStatsBar from './components/query/CorpusStatsBar';
import BootstrapModal from './components/BootstrapModal';

function MainPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { result, loading, error, queryText, execute, loadCached, clear } = useQuery();

  const [filters, setFilters] = useState({});
  const [retrieval, setRetrieval] = useState({
    depth: 'standard',
    topK: 10,
    scoreThreshold: 0.60,
  });
  const [activeCitation, setActiveCitation] = useState(null);
  const [showTrace, setShowTrace] = useState(false);
  const [showFormatMenu, setShowFormatMenu] = useState(false);
  const [exportFormat, setExportFormat] = useState('pdf');
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 });
  const chevronRef = useRef(null);

  const handleSubmit = useCallback((text) => {
    setActiveCitation(null);
    setShowTrace(false);
    const { _datePreset, ...apiFilters } = filters;
    execute(text, apiFilters, {
      query_depth: retrieval.depth,
      top_k: retrieval.topK,
      score_threshold: retrieval.scoreThreshold,
    });
  }, [execute, filters, retrieval]);

  const handleNewQuery = useCallback(() => {
    clear();
    setSearchParams({});
  }, [clear, setSearchParams]);

  const cachedQueryId = searchParams.get('q');
  useEffect(() => {
    if (cachedQueryId) loadCached(cachedQueryId);
  }, [cachedQueryId]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeCitationObj = useMemo(() => {
    if (activeCitation == null || !result?.citations) return null;
    return result.citations.find((c) => c.index === activeCitation) || null;
  }, [activeCitation, result?.citations]);

  const sameDocCitations = useMemo(() => {
    if (!activeCitationObj || !result?.citations) return [];
    return result.citations.filter((c) => c.document_id === activeCitationObj.document_id);
  }, [activeCitationObj, result?.citations]);

  const handlePrevChunk = useCallback(() => {
    const idx = sameDocCitations.findIndex((c) => c.index === activeCitation);
    if (idx > 0) setActiveCitation(sameDocCitations[idx - 1].index);
  }, [sameDocCitations, activeCitation]);

  const handleNextChunk = useCallback(() => {
    const idx = sameDocCitations.findIndex((c) => c.index === activeCitation);
    if (idx < sameDocCitations.length - 1) setActiveCitation(sameDocCitations[idx + 1].index);
  }, [sameDocCitations, activeCitation]);

  const hasPrev = sameDocCitations.length > 1 && sameDocCitations.findIndex((c) => c.index === activeCitation) > 0;
  const hasNext = sameDocCitations.length > 1 && sameDocCitations.findIndex((c) => c.index === activeCitation) < sameDocCitations.length - 1;

  const handleExport = useCallback(async (fmt) => {
    setShowFormatMenu(false);
    if (!result?.query_id) return;
    try {
      const data = await exportQuery(result.query_id, fmt);
      if (fmt === 'json') {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `regpulse-export-${result.query_id}.json`; a.click();
        URL.revokeObjectURL(url);
      } else {
        const url = URL.createObjectURL(data);
        const a = document.createElement('a');
        a.href = url; a.download = `regpulse-export-${result.query_id}.pdf`; a.click();
        URL.revokeObjectURL(url);
      }
    } catch (_) {}
  }, [result?.query_id]);

  // Drawer: open for citation OR for trace
  const drawerOpen = !!activeCitationObj || showTrace;
  const drawerInitialTab = showTrace && !activeCitationObj ? 'trace' : 'chunk';

  const isLanding = !result && !loading && !error;

  return (
    <>
      <div className={`rp-main-page${isLanding ? ' landing' : ''}`}>
        <div className="rp-content-inner">
          <div className="container">
            {/* Query input area — always at top (or vertically centred on landing) */}
            <div className="rp-query-area">
              {isLanding && (
                <div className="rp-ask-lbl">Ask a regulatory question</div>
              )}
              <div className={`rp-query-bar${loading ? ' thinking' : ''}`}>
                <QueryInput
                  key={queryText}
                  value={queryText}
                  onSubmit={handleSubmit}
                  disabled={loading}
                />
                {loading && (
                  <>
                    <div className="rp-thinking-bar" />
                    <div className="rp-thinking-meta">
                      Searching {result?.retrieval_params_applied?.sub_query_count || retrieval.topK} variations across indexed documents...
                    </div>
                  </>
                )}
              </div>
              <FilterBar
                filters={filters}
                onChange={setFilters}
                retrieval={retrieval}
                onRetrievalChange={setRetrieval}
              />
            </div>

            {/* Landing suggestions */}
            {isLanding && <EmptyState onSubmit={handleSubmit} disabled={loading} />}

            {/* Error */}
            {error && (
              <div style={{ padding: 24, background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)', marginTop: 24 }}>
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

                {/* Export split button */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12, padding: '0 18px' }}>
                  <div style={{ display: 'flex', height: 34, borderRadius: 6, border: '1px solid #4a5568', overflow: 'hidden' }}>
                    <button
                      onClick={() => handleExport(exportFormat)}
                      style={{ height: 34, padding: '0 14px', fontSize: 13, background: 'transparent', border: 'none', borderRight: '1px solid #4a5568', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, color: 'var(--doc-text)' }}
                    >
                      Export
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M8 3v8M4 7l4 4 4-4M3 13h10"/>
                      </svg>
                    </button>
                    <button
                      ref={chevronRef}
                      onClick={() => {
                        if (chevronRef.current) {
                          const r = chevronRef.current.getBoundingClientRect();
                          setMenuPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
                        }
                        setShowFormatMenu((m) => !m);
                      }}
                      style={{ height: 34, padding: '0 8px', background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', color: 'var(--doc-text)' }}
                    >
                      <svg width="10" height="10" viewBox="0 0 10 6" fill="currentColor"><path d="M0 0l5 6 5-6z"/></svg>
                    </button>
                  </div>
                </div>

                <QueryExpansion subQueries={result.sub_queries} />

                {result.citations && result.citations.length > 0 && (
                  <>
                    <div className="rp-sources-head">
                      <div className="rp-sources-lbl">
                        Sources <span className="count">({result.citations.length})</span>
                      </div>
                    </div>
                    <div className="rp-cit-list">
                      {result.citations.map((c) => (
                        <CitationCard
                          key={c.index}
                          citation={c}
                          isActive={activeCitation === c.index}
                          onClick={() => setActiveCitation(c.index === activeCitation ? null : c.index)}
                          onViewSource={() => { setShowTrace(false); setActiveCitation(c.index); }}
                        />
                      ))}
                    </div>
                  </>
                )}

                {(!result.citations || result.citations.length === 0) && result.answer && (
                  <div style={{ marginTop: 24, padding: 16, background: 'var(--doc-bg)', border: '1px solid var(--doc-border)', borderRadius: 4, fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--doc-text-2)', textAlign: 'center' }}>
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
          onViewTrace={() => { setShowTrace(true); }}
        />
      </div>

      {/* Overlay drawer — covers everything, no layout shift */}
      {drawerOpen && (
        <SourcePanel
          citation={activeCitationObj}
          traceId={result?.langfuse_trace_id}
          initialTab={drawerInitialTab}
          onClose={() => { setActiveCitation(null); setShowTrace(false); }}
          onPrevChunk={handlePrevChunk}
          onNextChunk={handleNextChunk}
          hasPrev={hasPrev}
          hasNext={hasNext}
        />
      )}

      {/* Export format menu */}
      {showFormatMenu && createPortal(
        <div style={{ position: 'fixed', top: menuPos.top, right: menuPos.right, border: '1px solid #4a5568', borderRadius: 6, background: 'var(--doc-surface)', zIndex: 1000 }}>
          {['PDF', 'JSON'].map((fmt) => (
            <div
              key={fmt}
              onClick={() => { setExportFormat(fmt.toLowerCase()); setShowFormatMenu(false); }}
              style={{ padding: '8px 16px', cursor: 'pointer', fontSize: 13, color: 'var(--doc-text)' }}
            >
              {fmt}
            </div>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}

export default function App() {
  const [resetKey, setResetKey] = useState(0);
  const navigate = useNavigate();
  const modelStatus = useModelStatus();
  const [showBootstrapModal, setShowBootstrapModal] = useState(false);

  useEffect(() => {
    getBootstrapState().then((s) => {
      if (s.doc_count === 0) setShowBootstrapModal(true);
    }).catch(() => {});
  }, []);

  const handleNewQuery = useCallback(() => {
    navigate('/', { replace: true });
    setResetKey((k) => k + 1);
  }, [navigate]);

  return (
    <ModelStatusContext.Provider value={modelStatus}>
    <div className="app-shell">
      <Sidebar onNewQuery={handleNewQuery} modelStatus={modelStatus} />
      <div className="main-column">
        <TopNav />
        <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <Routes>
            <Route path="/" element={<QueryPage key={resetKey} />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/corpus" element={<CorpusPage />} />
            <Route path="/corpus/:docId" element={<DocumentDetailPage />} />
            <Route path="/corpus/runs" element={<Navigate to="/ingestions" replace />} />
            <Route path="/ingestions" element={<IngestionsPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
        <CorpusStatsBar />
      </div>
    </div>
    {showBootstrapModal && (
      <BootstrapModal
        onClose={() => setShowBootstrapModal(false)}
        onStarted={() => {}}
      />
    )}
    </ModelStatusContext.Provider>
  );
}
