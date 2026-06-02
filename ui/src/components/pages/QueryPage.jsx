import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import FilterBar from '../layout/FilterBar';
import QueryInput from '../query/QueryInput';
import QueryExpansion from '../query/QueryExpansion';
import AuditFooter from '../query/AuditFooter';
import EmptyState from '../query/EmptyState';
import useQuery from '../../hooks/useQuery';
import { exportQuery, getPdfPage } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

const DOCTYPE_LABEL = {
  drug_approval: 'Drug Approval', guidance: 'Guidance', press_release: 'Press Release',
  safety_alert: 'Safety Alert', reflection_paper: 'Reflection Paper',
  news_item: 'News Item', other: 'Unclassified',
};

function getSplitRatio(answerText) {
  const len = answerText?.length ?? 0;
  if (len < 300) return 'r40';
  if (len <= 600) return 'r50';
  return 'r60';
}

function renderAnswer(text, selectedIdx, onCitationClick) {
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
      parts.push(
        <span
          key={`c-${m.index}`}
          className={`g2-cmark${selectedIdx === n ? ' active' : ''}`}
          data-testid={`citation-${n}`}
          onClick={() => onCitationClick(n)}
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

function SrcPill({ src }) {
  const map = {
    n8n_rss: ['n8n', 'n8n RSS'], bootstrap_ui: ['bootstrap', 'Bootstrap'],
    manual_cli: ['manual', 'Manual'], scheduled: ['n8n', 'Scheduled'], manual: ['manual', 'Manual'],
  };
  const [cls, label] = map[src] || ['manual', src || '—'];
  return <span className={`g2-srcpill ${cls}`}>{label}</span>;
}

function CopyIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
    </svg>
  );
}

function ExtIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

function PdfIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 3v8M4 7l4 4 4-4M3 13h10" />
    </svg>
  );
}

// ── Source origin panel (left) ─────────────────────────────────────────────

function SourcePanel({ chunk, onViewSource }) {
  if (!chunk) return (
    <div className="g2-panel side" data-testid="provenance-source-panel">
      <div className="g2-panel-lbl">Source Origin <span className="sub">· where it came from</span></div>
      <div className="g2-empty">Select a citation</div>
    </div>
  );

  const dash = (v) => (v == null || v === '') ? '—' : v;

  return (
    <div className="g2-panel side" data-testid="provenance-source-panel">
      <div className="g2-panel-lbl">Source Origin <span className="sub">· where it came from</span></div>
      <div className="g2-panel-scroll">
        <div className="g2-src-title">{chunk.document_title || chunk.document_id || '—'}</div>
        <div className="g2-src-field">
          <span className="k">Agency</span>
          <span className="g2-agency-pill">{chunk.issuing_body || chunk.agency || '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Doc type</span>
          <span className="v">{DOCTYPE_LABEL[chunk.doc_type] || chunk.doc_type || '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Publication date</span>
          <span className="v mono">{formatDate(chunk.publication_date) || '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Clause ID</span>
          <span className="v mono">{dash(chunk.clause_id)}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Page</span>
          <span className="v muted">{chunk.page_no != null ? `Page ${chunk.page_no}` : '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Source URL</span>
          <span className="v">
            {chunk.source_url
              ? <a href={chunk.source_url} target="_blank" rel="noreferrer">{chunk.source_url} <ExtIcon /></a>
              : '—'}
          </span>
        </div>
      </div>
      <div className="g2-panel-action">
        <button
          className={`g2-btn-outline${!chunk.source_local_path && !chunk.source_url ? ' disabled' : ''}`}
          data-testid="view-source-btn"
          onClick={onViewSource}
          disabled={!chunk.source_local_path && !chunk.source_url}
        >
          <PdfIcon /> View Source
        </button>
      </div>
    </div>
  );
}

// ── Chunk list + text panel (middle) ──────────────────────────────────────

function ChunkPanel({ chunks, selectedIdx, onSelect, loading }) {
  const [showFull, setShowFull] = useState(false);
  const selectedChunk = chunks?.find((c) => c.index === selectedIdx) || chunks?.[0];
  const chunkText = selectedChunk?.chunk_text || '';
  const isLong = chunkText.length > 500;

  useEffect(() => setShowFull(false), [selectedIdx]);

  if (loading) {
    return (
      <div className="g2-panel" data-testid="provenance-chunk-panel">
        <div className="g2-panel-lbl">Contributing Chunks <span className="sub">· loading</span></div>
        <div className="g2-panel-scroll" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {[1, 2, 3].map((i) => (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div className="g2-skel" style={{ width: '80%' }} />
              <div className="g2-skel" style={{ width: '40%', height: 9 }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!chunks?.length) return (
    <div className="g2-panel" data-testid="provenance-chunk-panel">
      <div className="g2-panel-lbl">Contributing Chunks</div>
      <div className="g2-empty">No chunks available</div>
    </div>
  );

  const total = chunks.length;

  return (
    <div className="g2-panel" data-testid="provenance-chunk-panel">
      <div className="g2-panel-lbl">Contributing Chunks <span className="sub">· {total}</span></div>
      <div className="g2-panel-scroll" style={{ padding: 0, minHeight: 0 }}>
        <div className="g2-chunk-list">
          {chunks.map((c) => {
            const dots = Math.max(0, Math.round((c.score || 0) * 3));
            return (
              <div
                key={c.index}
                className={`g2-chunk-row${c.index === selectedIdx ? ' on' : ''}`}
                data-testid={`chunk-row-${c.chunk_id || c.index}`}
                onClick={() => onSelect(c.index)}
              >
                <span className="rank">{c.relevance_rank || c.index}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="ct">{c.document_title || c.document_id}</div>
                  <div className="cc">
                    <span>{c.clause_id || '—'}</span>
                    <span className="g2-dots">
                      {[0, 1, 2].map((i) => <i key={i} className={i < dots ? 'on' : ''} />)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {selectedChunk && (
        <div className="g2-chunk-text-wrap">
          <div className="g2-chunk-text-lbl">Chunk text</div>
          <div className="g2-chunk-text" data-testid={`chunk-text-${selectedChunk.chunk_id || selectedChunk.index}`}>
            {showFull || !isLong ? chunkText : chunkText.slice(0, 300) + '…'}
            {isLong && (
              <span className="g2-showmore" onClick={() => setShowFull((f) => !f)}>
                {showFull ? ' Show less' : ' Show more'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Ingestion trace panel (right) ─────────────────────────────────────────

function TracePanel({ chunk }) {
  const [copied, setCopied] = useState(false);

  const copyChunkId = () => {
    if (chunk?.chunk_id) {
      navigator.clipboard?.writeText(chunk.chunk_id).catch(() => {});
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  if (!chunk) return (
    <div className="g2-panel side" data-testid="provenance-trace-panel">
      <div className="g2-panel-lbl">Ingestion Trace <span className="sub">· where it ended up</span></div>
      <div className="g2-empty">Select a citation</div>
    </div>
  );

  return (
    <div className="g2-panel side" data-testid="provenance-trace-panel">
      <div className="g2-panel-lbl">Ingestion Trace <span className="sub">· where it ended up</span></div>
      <div className="g2-panel-scroll">
        <div className="g2-src-field">
          <span className="k">Ingestion source</span>
          <span className="g2-src-pill-row"><SrcPill src={chunk.ingestion_source} /></span>
        </div>
        <div className="g2-src-field">
          <span className="k">Triggered by</span>
          <span className="v muted">{chunk.triggered_by || '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Ingested at</span>
          <span className="v mono">{formatDateTime(chunk.ingested_at) || '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Embedding model</span>
          <span className="v mono">{chunk.embedding_model || '—'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Collection</span>
          <span className="v mono">{chunk.collection || 'knowledge_base'}</span>
        </div>
        <div className="g2-src-field">
          <span className="k">Chunk ID</span>
          <span className="v mono" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }}>
              {chunk.chunk_id || '—'}
            </span>
            {chunk.chunk_id && (
              <span className="g2-copy" title={copied ? 'Copied!' : 'Copy chunk ID'} onClick={copyChunkId}>
                <CopyIcon />
              </span>
            )}
          </span>
        </div>
      </div>
      <div className="g2-panel-action">
        {chunk.langfuse_url ? (
          <a
            className="g2-btn-outline"
            href={chunk.langfuse_url}
            target="_blank"
            rel="noreferrer"
            data-testid="view-langfuse-btn"
            style={{ textDecoration: 'none' }}
          >
            <ExtIcon /> View in Langfuse
          </a>
        ) : (
          <button
            className="g2-btn-outline disabled"
            title="Trace not available for this document."
          >
            <ExtIcon /> View in Langfuse
          </button>
        )}
      </div>
    </div>
  );
}

// ── PDF modal ─────────────────────────────────────────────────────────────

function PdfModal({ chunk, onClose }) {
  const [imgSrc, setImgSrc] = useState(null);
  const [pageNo, setPageNo] = useState(chunk?.page_no ?? 1);

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
          <span className="pg">Page {pageNo}</span>
          <button className="close" onClick={onClose}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="g2-pdf-stage">
          {imgSrc ? (
            <img src={imgSrc} alt={`Page ${pageNo}`} onError={() => setImgSrc(null)} />
          ) : chunk?.source_url ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-2)', fontSize: 13.5 }}>
              <p>PDF preview not available for this document.</p>
              <a href={chunk.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-l)' }}>
                Open source document <ExtIcon />
              </a>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--doc-text-3)', fontSize: 13.5 }}>
              PDF not available
            </div>
          )}
        </div>
        {chunk?.source_local_path && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, padding: '10px 16px', borderTop: '1px solid var(--doc-border)' }}>
            <button
              style={{ padding: '4px 12px', background: 'var(--doc-surface)', border: '1px solid var(--doc-border-strong)', borderRadius: 4, cursor: 'pointer', color: 'var(--doc-text)', fontSize: 12 }}
              onClick={() => setPageNo((p) => Math.max(1, p - 1))}
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

// ── Main QueryPage ─────────────────────────────────────────────────────────

export default function QueryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { result, loading, error, queryText, execute, loadCached, clear } = useQuery();

  const [filters, setFilters] = useState({});
  const [retrieval, setRetrieval] = useState({ depth: 'standard', topK: 10, scoreThreshold: 0.60 });
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [pdfOpen, setPdfOpen] = useState(false);
  const [showFormatMenu, setShowFormatMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 });
  const [exportFormat, setExportFormat] = useState('pdf');
  const chevRef = useRef(null);

  const handleSubmit = useCallback((text) => {
    setSelectedIdx(null);
    setPdfOpen(false);
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
    setSelectedIdx(null);
    setPdfOpen(false);
  }, [clear, setSearchParams]);

  const cachedQueryId = searchParams.get('q');
  useEffect(() => {
    if (cachedQueryId) loadCached(cachedQueryId);
  }, [cachedQueryId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-select first chunk on result arrival
  useEffect(() => {
    if (result?.citations?.length > 0) {
      setSelectedIdx(result.citations[0].index);
    }
  }, [result?.query_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedChunk = useMemo(() => {
    if (selectedIdx == null || !result?.citations) return null;
    return result.citations.find((c) => c.index === selectedIdx) || result.citations[0] || null;
  }, [selectedIdx, result?.citations]);

  const handleCitationClick = useCallback((n) => {
    setSelectedIdx((prev) => prev === n ? prev : n);
  }, []);

  const handleExport = useCallback(async (fmt) => {
    setShowFormatMenu(false);
    if (!result?.query_id) return;
    try {
      const data = await exportQuery(result.query_id, fmt);
      const blob = fmt === 'json' ? new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }) : data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `regpulse-export-${result.query_id}.${fmt}`; a.click();
      URL.revokeObjectURL(url);
    } catch (_) {}
  }, [result?.query_id]);

  const isLanding = !result && !loading && !error;
  const hasResult = !!result;
  const splitRatio = getSplitRatio(result?.answer);
  const routingPath = result?.routing_path;
  const isMetadata = routingPath === 'METADATA';
  const citations = result?.citations || [];

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
        <AuditFooter />
      </div>
    );
  }

  return (
    <div className="g2" style={{ position: 'relative' }}>
      {/* ── Top: query bar + answer ── */}
      <div className={`g2-answer ${hasResult ? splitRatio : 'r50'}`} data-testid="query-answer-region">
        {/* Query input strip */}
        <div className="g2-query-area">
          <div className="g2-query-area-inner">
            <div className="rp-query-bar" style={{ marginBottom: 8 }}>
              <QueryInput key={queryText} value={queryText} onSubmit={handleSubmit} disabled={loading} />
            </div>
            <FilterBar filters={filters} onChange={setFilters} retrieval={retrieval} onRetrievalChange={setRetrieval} />
          </div>
        </div>

        <div className="g2-answer-scroll">
          <div className="g2-answer-inner">
            {loading ? (
              <>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
                  <div className="g2-skel" style={{ width: '92%' }} />
                  <div className="g2-skel" style={{ width: '98%' }} />
                  <div className="g2-skel" style={{ width: '76%' }} />
                  <div className="g2-skel" style={{ width: '88%', marginTop: 8 }} />
                  <div className="g2-skel" style={{ width: '65%' }} />
                </div>
                <div style={{ marginTop: 10, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-3)' }}>
                  Searching across indexed documents…
                </div>
              </>
            ) : error ? (
              <div style={{ padding: 16, background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', borderRadius: 4, color: 'var(--err-text)', fontSize: 13 }}>
                {error}
              </div>
            ) : result ? (
              <>
                <div className="g2-qbar">
                  <div className="g2-qtext">{queryText}</div>
                  <div className="g2-route">
                    <button className={routingPath === 'CONTENT' ? 'on' : ''}>CONTENT</button>
                    <button className={routingPath === 'METADATA' ? 'on' : ''}>METADATA</button>
                  </div>
                  <div style={{ position: 'relative' }}>
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
                <div className="g2-qmeta">
                  query {result.query_id?.slice(0, 8)} · {formatDateTime(result.timestamp, true)} · {routingPath} routing · {citations.length} chunk{citations.length !== 1 ? 's' : ''} cited
                </div>

                <div className="g2-answer-body">
                  {renderAnswer(result.answer, selectedIdx, handleCitationClick)}
                  <p className="g2-disc">
                    AI-generated answer based on retrieved regulatory documents. Verify critical requirements against current source documents. Queries requiring legal interpretation should be referred to a qualified regulatory professional.
                  </p>
                </div>

                <QueryExpansion subQueries={result.sub_queries} />
              </>
            ) : null}
          </div>
        </div>

        {result && (
          <AuditFooter
            queryId={result?.query_id}
            timestamp={result?.timestamp}
            routingPath={result?.routing_path}
            onViewTrace={() => {}}
          />
        )}
      </div>

      {/* ── Bottom: 3 provenance panels ── */}
      <div className="g2-prov" data-testid="query-provenance-region">
        {loading ? (
          <>
            <div className="g2-panel side">
              <div className="g2-panel-lbl">Source Origin</div>
              <div className="g2-panel-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {[1, 2, 3].map((i) => <div key={i} className="g2-skel" style={{ width: `${60 + i * 10}%` }} />)}
              </div>
            </div>
            <ChunkPanel chunks={[]} selectedIdx={null} onSelect={() => {}} loading={true} />
            <div className="g2-panel side">
              <div className="g2-panel-lbl">Ingestion Trace</div>
              <div className="g2-panel-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {[1, 2, 3].map((i) => <div key={i} className="g2-skel" style={{ width: `${50 + i * 12}%` }} />)}
              </div>
            </div>
          </>
        ) : isMetadata || !citations.length ? (
          <div className="g2-empty" style={{ gridColumn: '1 / -1' }}>
            {isMetadata ? 'No chunk provenance available for metadata queries' : 'Ask a question to see source provenance'}
          </div>
        ) : (
          <>
            <SourcePanel chunk={selectedChunk} onViewSource={() => setPdfOpen(true)} />
            <ChunkPanel
              chunks={citations}
              selectedIdx={selectedIdx}
              onSelect={setSelectedIdx}
              loading={false}
            />
            <TracePanel chunk={selectedChunk} />
          </>
        )}
      </div>

      {/* PDF modal */}
      {pdfOpen && selectedChunk && (
        <PdfModal chunk={selectedChunk} onClose={() => setPdfOpen(false)} />
      )}

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
              onClick={() => { setExportFormat(fmt.toLowerCase()); handleExport(fmt.toLowerCase()); }}
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
