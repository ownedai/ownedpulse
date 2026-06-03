import { useState, useCallback, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import FilterBar from '../layout/FilterBar';
import QueryInput from '../query/QueryInput';
import QueryExpansion from '../query/QueryExpansion';
import EmptyState from '../query/EmptyState';
import useQuery from '../../hooks/useQuery';
import { exportQuery, getPdfPage, getQueryTrace } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

// ── Constants ──────────────────────────────────────────────────────────────

const QUERY_STATES = { IDLE: 'idle', ANSWER: 'answer', TRACEABILITY: 'traceability' };

const DOCTYPE_LABEL = {
  drug_approval: 'Drug Approval', guidance: 'Guidance', press_release: 'Press Release',
  safety_alert: 'Safety Alert', reflection_paper: 'Reflection Paper',
  news_item: 'News Item', other: 'Unclassified',
};

const INGESTION_SOURCE_LABELS = {
  manual_cli: 'Manual (CLI)', bootstrap_ui: 'Bootstrap (Initial load)', n8n_rss: 'Scheduled (RSS)',
};

// ── SVG Icons ──────────────────────────────────────────────────────────────

function CloseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}
function ChevronIcon({ open }) {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d={open ? 'M2 8l4-4 4 4' : 'M2 4l4 4 4-4'} />
    </svg>
  );
}
function ChevRightIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M4 2l4 4-4 4" />
    </svg>
  );
}
function ExtIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
      <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}
function PdfIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
    </svg>
  );
}
function DownloadIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M8 3v8M4 7l4 4 4-4M3 13h10" />
    </svg>
  );
}

// ── Answer text renderer ───────────────────────────────────────────────────

function renderAnswer(text, selectedChunkId, citations, onCitationClick) {
  if (!text) return null;
  const normalised = text
    .replace(/\n{1,2}(\[\d+\])\n([.,])/g, ' $1$2')
    .replace(/(\[\d+\])\s*\./g, '$1.')
    .replace(/\s*\.\s*(\[\d+\])/g, '$1.');

  const paragraphs = normalised.split('\n\n').filter((p) => p.trim());

  return paragraphs.map((para, i) => {
    const parts = [];
    let last = 0;
    const re = /\[(\d+)\]/g;
    let m;
    while ((m = re.exec(para)) !== null) {
      if (m.index > last) parts.push(para.slice(last, m.index));
      const n = parseInt(m[1], 10);
      const chunkForN = citations?.find((c) => c.index === n);
      const isActive = chunkForN && chunkForN.chunk_id === selectedChunkId;
      parts.push(
        <span
          key={`c-${m.index}`}
          className={`g2v2-cmark${isActive ? ' on' : ''}`}
          data-testid={`citation-${n}`}
          onClick={() => onCitationClick(n)}
          title={`Citation [${n}]`}
        >
          {n}
        </span>
      );
      last = m.index + m[0].length;
    }
    if (last < para.length) parts.push(para.slice(last));
    return <p key={i}>{parts}</p>;
  });
}

// ── Traceability Panel — LLM Call block ──────────────────────────────────

function LlmCallBlock({ queryId }) {
  const [open, setOpen] = useState(true);
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!queryId) return;
    setLoading(true);
    setError(false);
    getQueryTrace(queryId)
      .then((d) => {
        if (d?.error) setError(true);
        else setTrace(d);
        setLoading(false);
      })
      .catch(() => { setError(true); setLoading(false); });
  }, [queryId]);

  const dash = (v) => (v == null || v === 0) ? '—' : v;

  const summaryLine = trace
    ? `${trace.model || '—'} · ${trace.input_tokens ? trace.input_tokens.toLocaleString() : '—'} tokens · ${trace.latency_ms ? (trace.latency_ms / 1000).toFixed(1) + 's' : '—'}`
    : '';

  return (
    <div className="g2v2-block" data-testid="llm-call-block">
      <div className="g2v2-block-head" onClick={() => setOpen((v) => !v)}>
        <span className="lhs">
          <span className={`chev${open ? ' open' : ''}`}><ChevRightIcon /></span>
          <span className="name">LLM Call</span>
        </span>
        {!open && !loading && !error && (
          <span className="summary">{summaryLine}</span>
        )}
      </div>
      {open && (
        <div className="g2v2-block-body">
          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 8 }}>
              {[1, 2, 3].map((i) => <div key={i} className="g2-skel" style={{ width: `${50 + i * 15}%`, height: 11 }} />)}
            </div>
          )}
          {error && (
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)', paddingTop: 8 }}>
              Trace data unavailable — Langfuse may be unreachable
            </div>
          )}
          {trace && (
            <div className="g2v2-llm-grid">
              <span className="k">model</span><span className="v">{dash(trace.model)}</span>
              <span className="k">timestamp</span><span className="v">{trace.timestamp ? formatDateTime(trace.timestamp, true) : '—'}</span>
              <span className="k">input tokens</span><span className="v">{trace.input_tokens ? trace.input_tokens.toLocaleString() : '—'}</span>
              <span className="k">output tokens</span><span className="v">{trace.output_tokens ? trace.output_tokens.toLocaleString() : '—'}</span>
              <span className="k">latency</span><span className="v">{trace.latency_ms ? `${(trace.latency_ms / 1000).toFixed(1)}s` : '—'}</span>
              <span className="k">prompt version</span><span className="v">{dash(trace.system_prompt_version)}</span>
              <span className="k">chunks in context</span><span className="v">
                {trace.chunks_sent_to_context != null
                  ? `${trace.chunks_sent_to_context}${trace.chunks_retrieved != null ? ` of ${trace.chunks_retrieved} retrieved` : ''}`
                  : '—'}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Traceability Panel — Chunk card ──────────────────────────────────────

function ChunkCard({ chunk, highlighted, onViewSource }) {
  const [showMore, setShowMore] = useState(false);
  const text = chunk.chunk_text || '';
  const isLong = text.length > 300;

  useEffect(() => {
    if (highlighted) setShowMore(false);
  }, [highlighted]);

  const agency = chunk.issuing_body || chunk.agency || '—';
  const ingDate = chunk.ingested_at ? formatDate(chunk.ingested_at) : '—';
  const srcLabel = INGESTION_SOURCE_LABELS[chunk.ingestion_source] || chunk.ingestion_source || '—';

  return (
    <div
      className={`g2v2-chunk${highlighted ? ' pulse' : ''}`}
      data-testid={`chunk-card-${chunk.chunk_id}`}
    >
      <div className="ch-top">
        <span className="ch-badge">{chunk.index}</span>
        <span className="ch-title">{chunk.document_title || chunk.document_id || '—'}</span>
        <span className="ch-agency">{agency}</span>
      </div>
      <div className="ch-meta">
        <span><span className="k">clause</span> <span className="v">{chunk.clause_id || '—'}</span></span>
        <span><span className="k">page</span> <span className="v">{chunk.page_no != null ? chunk.page_no + 1 : '—'}</span></span>
        <span><span className="k">type</span> <span className="v">{DOCTYPE_LABEL[chunk.doc_type] || chunk.doc_type || '—'}</span></span>
        <span><span className="k">published</span> <span className="v">{formatDate(chunk.publication_date) || '—'}</span></span>
      </div>
      <div className="ch-text">
        {isLong && !showMore ? text.slice(0, 300) + '… ' : text}
        {isLong && (
          <span className="ch-showmore" onClick={() => setShowMore((v) => !v)}>
            {showMore ? 'Show less' : 'Show more'}
          </span>
        )}
      </div>
      <div className="ch-foot">
        <span className="ch-ingest">{ingDate} · {srcLabel} · {chunk.embedding_model || 'mxbai-embed-large'}</span>
        <button
          className="ch-view"
          data-testid={`chunk-view-source-${chunk.chunk_id}`}
          onClick={() => onViewSource(chunk)}
        >
          <PdfIcon /> View Source
        </button>
      </div>
    </div>
  );
}

// ── Traceability Panel ────────────────────────────────────────────────────

function TraceabilityPanel({ queryId, citations, selectedChunkId, onChunkSelect, onClose, onViewSource }) {
  const [uncitedOpen, setUncitedOpen] = useState(false);

  const cited = citations.filter((c) => c.cited_by_llm);
  const uncited = citations.filter((c) => !c.cited_by_llm);

  // Scroll selected chunk into view when it changes
  const panelRef = useRef(null);
  useEffect(() => {
    if (!selectedChunkId || !panelRef.current) return;
    const el = panelRef.current.querySelector(`[data-testid="chunk-card-${selectedChunkId}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [selectedChunkId]);

  return (
    <div className="g2v2-panel" data-testid="traceability-panel">
      <div className="g2v2-panel-head">
        <span className="t">Traceability</span>
        <button className="close" data-testid="traceability-close" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      <div className="g2v2-panel-scroll" ref={panelRef}>

        {/* LLM Call */}
        <LlmCallBlock queryId={queryId} />

        {/* Cited chunks */}
        <div className="g2v2-section-lbl" data-testid="cited-chunks-block">
          Cited chunks · {cited.length}
        </div>
        {cited.map((chunk) => (
          <ChunkCard
            key={chunk.chunk_id}
            chunk={chunk}
            highlighted={chunk.chunk_id === selectedChunkId}
            onViewSource={onViewSource}
          />
        ))}

        {/* Uncited chunks */}
        {uncited.length > 0 && (
          <div className="g2v2-block" data-testid="uncited-chunks-block" style={{ marginTop: 4 }}>
            <div className="g2v2-block-head" onClick={() => setUncitedOpen((v) => !v)}>
              <span className="lhs">
                <span className={`chev${uncitedOpen ? ' open' : ''}`}><ChevRightIcon /></span>
                <span className="name">Retrieved · not cited</span>
              </span>
              <span className="summary">{uncited.length} chunk{uncited.length !== 1 ? 's' : ''}</span>
            </div>
            {uncitedOpen && (
              <div style={{ borderTop: '1px solid var(--doc-border)' }}>
                {uncited.map((u) => (
                  <div key={u.chunk_id} className="g2v2-uncited">
                    <span className="u-agency">{u.issuing_body || u.agency || '—'}</span>
                    <span className="u-title">{u.document_title || u.document_id || '—'}</span>
                    <span className="u-score">{u.score != null ? u.score.toFixed(2) : '—'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── PDF Modal ─────────────────────────────────────────────────────────────

function PdfModal({ chunk, onClose }) {
  const [imgSrc, setImgSrc] = useState(null);
  const [pageNo, setPageNo] = useState(chunk?.page_no ?? 0);

  useEffect(() => {
    if (chunk?.source_local_path) {
      setImgSrc(getPdfPage(chunk.source_local_path, pageNo));
    } else {
      setImgSrc(null);
    }
  }, [chunk?.source_local_path, pageNo]);

  return (
    <div className="g2-pdf-modal" data-testid="pdf-modal" onClick={onClose}>
      <div className="g2-pdf-box" onClick={(e) => e.stopPropagation()}>
        <div className="g2-pdf-bar">
          <span className="t">{chunk?.document_title || 'Source Document'}</span>
          <span className="pg">Page {pageNo + 1}</span>
          <button className="close" onClick={onClose}><CloseIcon /></button>
        </div>
        <div className="g2-pdf-stage">
          {imgSrc ? (
            <img src={imgSrc} alt={`Page ${pageNo + 1}`} style={{ width: 540 }} onError={() => setImgSrc(null)} />
          ) : chunk?.source_url ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--doc-text-2)', fontSize: 13.5 }}>
              <p style={{ marginBottom: 12 }}>PDF preview not available for this document.</p>
              <a href={chunk.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-l)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                Open source document <ExtIcon />
              </a>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--doc-text-3)', fontSize: 13.5 }}>
              PDF not available
            </div>
          )}
        </div>
        {chunk?.source_local_path && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, padding: '10px 16px', borderTop: '1px solid var(--doc-border)' }}>
            <button
              style={{ padding: '4px 12px', background: 'var(--doc-surface)', border: '1px solid var(--doc-border-strong)', borderRadius: 4, cursor: 'pointer', color: 'var(--doc-text)', fontSize: 12 }}
              onClick={() => setPageNo((p) => Math.max(0, p - 1))}
              disabled={pageNo <= 0}
            >‹</button>
            <button
              style={{ padding: '4px 12px', background: 'var(--doc-surface)', border: '1px solid var(--doc-border-strong)', borderRadius: 4, cursor: 'pointer', color: 'var(--doc-text)', fontSize: 12 }}
              onClick={() => setPageNo((p) => p + 1)}
            >›</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Evidence Bar ──────────────────────────────────────────────────────────

function EvidenceBar({ citations, panelOpen, onOpenPanel }) {
  const titles = [...new Set(citations.map((c) => c.document_title || c.document_id).filter(Boolean))];
  const shown = titles.slice(0, 3);
  const extra = titles.length - 3;

  return (
    <div className="g2v2-evidence" data-testid="query-evidence-bar">
      <span className="ev-chunks">{citations.length} chunk{citations.length !== 1 ? 's' : ''} retrieved</span>
      <span className="ev-docs">
        {shown.map((t, i) => (
          <span key={t}>
            {i > 0 && ', '}
            <span className="d">{t.length > 40 ? t.slice(0, 40) + '…' : t}</span>
          </span>
        ))}
        {extra > 0 && <span>, +{extra} more</span>}
      </span>
      {!panelOpen && (
        <button
          className="g2v2-trace-btn"
          data-testid="query-traceability-btn"
          onClick={onOpenPanel}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
          </svg>
          View traceability →
        </button>
      )}
    </div>
  );
}

// ── Main QueryPage ─────────────────────────────────────────────────────────

export default function QueryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { result, loading, error, queryText, execute, loadCached, clear } = useQuery();

  const [filters, setFilters] = useState({});
  const [retrieval, setRetrieval] = useState({ depth: 'standard', topK: 10, scoreThreshold: 0.60 });

  const [queryState, setQueryState] = useState(QUERY_STATES.IDLE);
  const [selectedChunkId, setSelectedChunkId] = useState(null);
  const [pdfChunk, setPdfChunk] = useState(null);
  const [showFormatMenu, setShowFormatMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 });
  const chevRef = useRef(null);
  const answerRef = useRef(null);

  const handleSubmit = useCallback((text) => {
    setQueryState(QUERY_STATES.IDLE);
    setSelectedChunkId(null);
    setPdfChunk(null);
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
    setQueryState(QUERY_STATES.IDLE);
    setSelectedChunkId(null);
    setPdfChunk(null);
  }, [clear, setSearchParams]);

  const cachedQueryId = searchParams.get('q');
  useEffect(() => {
    if (cachedQueryId) loadCached(cachedQueryId);
  }, [cachedQueryId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Transition to ANSWER state when result arrives
  useEffect(() => {
    if (result) {
      setQueryState(QUERY_STATES.ANSWER);
      setSelectedChunkId(null);
    }
  }, [result?.query_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const citations = result?.citations || [];

  const handleCitationClick = useCallback((n) => {
    const chunk = citations.find((c) => c.index === n);
    if (!chunk) return;
    setSelectedChunkId(chunk.chunk_id);
    setQueryState(QUERY_STATES.TRACEABILITY);
    // Scroll citation badge into view in answer region
    setTimeout(() => {
      const el = answerRef.current?.querySelector(`[data-testid="citation-${n}"]`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
  }, [citations]);

  const handleOpenPanel = useCallback(() => {
    setQueryState(QUERY_STATES.TRACEABILITY);
  }, []);

  const handleClosePanel = useCallback(() => {
    setQueryState(QUERY_STATES.ANSWER);
    setSelectedChunkId(null);
  }, []);

  const handleChunkSelect = useCallback((chunkId) => {
    setSelectedChunkId(chunkId);
    // Scroll answer to corresponding citation
    const chunk = citations.find((c) => c.chunk_id === chunkId);
    if (chunk && answerRef.current) {
      const el = answerRef.current.querySelector(`[data-testid="citation-${chunk.index}"]`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [citations]);

  const handleViewSource = useCallback((chunk) => {
    setPdfChunk(chunk);
  }, []);

  const handleExport = useCallback(async (fmt) => {
    setShowFormatMenu(false);
    if (!result?.query_id) return;
    try {
      const data = await exportQuery(result.query_id, fmt);
      const blob = fmt === 'json'
        ? new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        : data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `regpulse-export-${result.query_id}.${fmt}`; a.click();
      URL.revokeObjectURL(url);
    } catch (_) {}
  }, [result?.query_id]);

  const isLanding = !result && !loading && !error;
  const panelOpen = queryState === QUERY_STATES.TRACEABILITY;
  const routingPath = result?.routing_path;
  const isMetadata = routingPath === 'METADATA';

  if (isLanding) {
    return (
      <div className="rp-main-page landing">
        <div className="rp-content-inner">
          <div className="container">
            <div className="rp-query-area">
              <div className="rp-ask-lbl">Ask a regulatory question</div>
              <div className="rp-query-bar">
                <QueryInput value={queryText} onSubmit={handleSubmit} disabled={false} />
              </div>
              <FilterBar filters={filters} onChange={setFilters} retrieval={retrieval} onRetrievalChange={setRetrieval} />
            </div>
            <EmptyState onSubmit={handleSubmit} disabled={false} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`g2v2${panelOpen ? ' open' : ''}`}>
      {/* Answer column */}
      <div className="g2v2-answer" data-testid="query-answer">
        <div className="g2v2-answer-scroll" ref={answerRef}>
          <div className="g2v2-answer-inner">

            {/* Query bar */}
            <div className="g2v2-qbar">
              <div className="g2v2-qtext" data-testid="query-input">
                <QueryInput key={queryText} value={queryText} onSubmit={handleSubmit} disabled={loading} compact />
              </div>
              {result && (
                <div className="g2v2-route">
                  <button className={routingPath === 'CONTENT' ? 'on' : ''}>CONTENT</button>
                  <button className={routingPath === 'METADATA' ? 'on' : ''}>METADATA</button>
                </div>
              )}
            </div>

            {/* Filter bar below query */}
            <div style={{ marginTop: 6 }}>
              <FilterBar filters={filters} onChange={setFilters} retrieval={retrieval} onRetrievalChange={setRetrieval} />
            </div>

            {/* Metadata strip */}
            {result && (
              <div className="g2v2-meta">
                q-{result.query_id?.slice(0, 8)} · {formatDateTime(result.timestamp, true)} · {routingPath} routing · {citations.length} chunk{citations.length !== 1 ? 's' : ''} retrieved
              </div>
            )}

            {/* Answer body */}
            {loading && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 16 }}>
                <div className="g2-skel" style={{ width: '92%' }} />
                <div className="g2-skel" style={{ width: '98%' }} />
                <div className="g2-skel" style={{ width: '76%' }} />
                <div className="g2-skel" style={{ width: '88%', marginTop: 8 }} />
                <div className="g2-skel" style={{ width: '65%' }} />
                <div style={{ marginTop: 6, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
                  Searching across indexed documents…
                </div>
              </div>
            )}
            {error && (
              <div style={{ marginTop: 16, padding: 16, background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)', fontSize: 13 }}>
                {error}
              </div>
            )}
            {result && (
              <div className="g2v2-body">
                {renderAnswer(result.answer, selectedChunkId, citations, handleCitationClick)}
                <p className="g2v2-disc">
                  AI-generated answer based on retrieved regulatory documents. Verify critical requirements against current source documents before relying on this response for compliance decisions.
                </p>
                <QueryExpansion subQueries={result.sub_queries} />

                {/* Export button */}
                <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end', position: 'relative' }}>
                  <button
                    className="g2-export"
                    ref={chevRef}
                    onClick={() => {
                      if (chevRef.current) {
                        const r = chevRef.current.getBoundingClientRect();
                        setMenuPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
                      }
                      setShowFormatMenu((m) => !m);
                    }}
                  >
                    <DownloadIcon /> Export
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Evidence bar — pinned below answer */}
        {result && !loading && !isMetadata && citations.length > 0 && (
          <EvidenceBar
            citations={citations}
            panelOpen={panelOpen}
            onOpenPanel={handleOpenPanel}
          />
        )}
        {result && !loading && isMetadata && (
          <div className="g2v2-evidence">
            <span className="ev-chunks" style={{ color: 'var(--doc-text-2)' }}>Metadata query — no chunk provenance</span>
          </div>
        )}
      </div>

      {/* Traceability panel */}
      {panelOpen && (
        <TraceabilityPanel
          queryId={result?.query_id}
          citations={citations}
          selectedChunkId={selectedChunkId}
          onChunkSelect={handleChunkSelect}
          onClose={handleClosePanel}
          onViewSource={handleViewSource}
        />
      )}

      {/* PDF modal */}
      {pdfChunk && <PdfModal chunk={pdfChunk} onClose={() => setPdfChunk(null)} />}

      {/* Export format menu */}
      {showFormatMenu && (
        <div
          style={{
            position: 'fixed', top: menuPos.top, right: menuPos.right,
            border: '1px solid var(--doc-border-strong)', borderRadius: 6,
            background: 'var(--doc-surface)', zIndex: 100,
          }}
          onMouseLeave={() => setShowFormatMenu(false)}
        >
          {['PDF', 'JSON'].map((fmt) => (
            <div
              key={fmt}
              onClick={() => handleExport(fmt.toLowerCase())}
              style={{ padding: '8px 16px', cursor: 'pointer', fontSize: 13, color: 'var(--doc-text)', whiteSpace: 'nowrap' }}
            >
              {fmt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
