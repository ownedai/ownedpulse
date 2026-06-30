import { useState, useCallback, useEffect, useRef, useContext } from 'react';
import { DEFAULT_RETRIEVAL } from '../../constants';
import { useSearchParams, Link } from 'react-router-dom';
import { ModelStatusContext } from '../../context/ModelStatusContext';
import FilterBar from '../layout/FilterBar';
import QueryInput from '../query/QueryInput';
import QueryExpansion from '../query/QueryExpansion';
import EmptyState from '../query/EmptyState';
import useQuery from '../../hooks/useQuery';
import { exportQuery, getPdfPage, getQueryTrace, getSystemPrompt, getChunkProvenance } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

// ── Constants ──────────────────────────────────────────────────────────────

const QUERY_STATES = { IDLE: 'idle', ANSWER: 'answer', TRACEABILITY: 'traceability' };

const DOCTYPE_LABEL = {
  drug_approval: 'Drug Approval', guidance: 'Guidance', press_release: 'Press Release',
  safety_alert: 'Safety Alert', reflection_paper: 'Reflection Paper',
  news_item: 'News Item', other: 'Unclassified',
};

const INGESTION_SOURCE_LABELS = {
  manual_cli: 'Manual (CLI)', bootstrap_ui: 'Bootstrap (Initial load)', scheduled: 'Scheduled',
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
function MaximizeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>
      <line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
    </svg>
  );
}
function MinimizeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="4 14 10 14 10 20"/><polyline points="20 4 14 4 14 10"/>
      <line x1="10" y1="14" x2="3" y2="21"/><line x1="21" y1="3" x2="14" y2="10"/>
    </svg>
  );
}

// ── Answer text renderer ───────────────────────────────────────────────────

const LEGAL_RE = /legal interpretation|qualified regulatory professional|not a substitute for regulatory|legal advice/i;

function renderAnswer(text, selectedChunkId, citations, onCitationClick) {
  if (!text) return { nodes: null, legalNote: null };
  const normalised = text
    .replace(/\n{1,2}(\[\d+\])\n([.,])/g, ' $1$2')
    .replace(/(\[\d+\])\s*\./g, '$1.')
    .replace(/\s*\.\s*(\[\d+\])/g, '$1.');

  const paragraphs = normalised.split('\n\n').filter((p) => p.trim());
  let legalNote = null;

  function renderInline(line) {
    const parts = [];
    const re = /\[(\d+)\]|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*/g;
    let last = 0;
    let m;
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) parts.push(line.slice(last, m.index));
      if (m[1] !== undefined) {
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
      } else if (m[2] !== undefined) {
        const label = m[2];
        const url = m[3].trim();
        if (url.startsWith('/')) {
          parts.push(
            <Link key={`l-${m.index}`} to={url} style={{ color: 'var(--accent-l)', textDecoration: 'none' }}>
              {label}
            </Link>
          );
        } else {
          parts.push(
            <a key={`l-${m.index}`} href={url} target="_blank" rel="noopener noreferrer"
              style={{ color: 'var(--accent-l)', textDecoration: 'none' }}>
              {label}
            </a>
          );
        }
      } else if (m[4] !== undefined) {
        parts.push(<strong key={`b-${m.index}`}>{m[4]}</strong>);
      }
      last = m.index + m[0].length;
    }
    if (last < line.length) parts.push(line.slice(last));
    return parts;
  }

  const nodes = paragraphs.map((para, i) => {
    if (LEGAL_RE.test(para)) {
      legalNote = para;
      return null;
    }
    const lines = para.split('\n').filter((l) => l.trim());

    // Numbered list
    const isNumbered = lines.length >= 1 && /^\d+\./.test(lines[0].trim());
    if (isNumbered) {
      // Try to parse as doc-link table: N. [title](url) · version · date
      const isDateStr = (s) => /^\d{2}\/\d{2}\/\d{4}$/.test(s.trim());
      const parsedRows = lines.map(line => {
        const content = line.replace(/^\d+\.\s*/, '');
        const m = content.match(/^\[([^\]]+)\]\(\s*([^)]+?)\s*\)(.*)/);
        if (!m) return null;
        const parts = m[3].split(/\s*·\s*/).filter(Boolean);
        let version = null, date = null;
        if (parts.length >= 2) { version = parts[0]; date = parts[1]; }
        else if (parts.length === 1) {
          if (isDateStr(parts[0])) date = parts[0]; else version = parts[0];
        }
        return { title: m[1], url: m[2].trim(), version, date };
      });

      if (parsedRows.every(r => r !== null)) {
        const hasVersion = parsedRows.some(r => r.version);
        const hasDate = parsedRows.some(r => r.date);
        return (
          <table key={i} className="rp-list-table">
            <thead>
              <tr>
                <th className="col-n">#</th>
                <th>Document</th>
                {hasVersion && <th className="col-ver">Version</th>}
                {hasDate && <th className="col-date">Published</th>}
              </tr>
            </thead>
            <tbody>
              {parsedRows.map((row, j) => (
                <tr key={j}>
                  <td className="col-n">{j + 1}</td>
                  <td>
                    <Link to={row.url} className="rp-list-link">{row.title}</Link>
                  </td>
                  {hasVersion && <td className="col-ver">{row.version || '—'}</td>}
                  {hasDate && <td className="col-date">{row.date || '—'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        );
      }

      return (
        <ol key={i} style={{ paddingLeft: 20, margin: '0 0 12px' }}>
          {lines.map((line, j) => (
            <li key={j} style={{ marginBottom: 5, lineHeight: 1.6 }}>
              {renderInline(line.replace(/^\d+\.\s*/, ''))}
            </li>
          ))}
        </ol>
      );
    }

    // Bullet list
    const isBullet = lines.length >= 1 && lines[0].trim().startsWith('- ');
    if (isBullet) {
      return (
        <ul key={i} style={{ paddingLeft: 20, margin: '0 0 12px' }}>
          {lines.map((line, j) => (
            <li key={j} style={{ marginBottom: 5, lineHeight: 1.6 }}>
              {renderInline(line.replace(/^-\s*/, ''))}
            </li>
          ))}
        </ul>
      );
    }

    return <p key={i}>{renderInline(lines.join(' '))}</p>;
  }).filter(Boolean);

  return { nodes, legalNote };
}

// ── System Prompt Modal ───────────────────────────────────────────────────

function PromptModal({ version, onClose }) {
  const [text, setText] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSystemPrompt()
      .then((d) => { setText(d.text); setLoading(false); })
      .catch(() => { setText(null); setLoading(false); });
  }, []);

  return (
    <div className="g2-pdf-modal" data-testid="prompt-modal" onClick={onClose}>
      <div
        className="g2-pdf-box"
        style={{ width: 640, maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="g2-pdf-bar">
          <span className="t">System prompt · {version}</span>
          <button className="close" onClick={onClose}><CloseIcon /></button>
        </div>
        <div style={{ overflowY: 'auto', padding: '20px 24px', flex: 1 }}>
          {loading && <div style={{ color: 'var(--doc-text-3)', fontSize: 13 }}>Loading…</div>}
          {!loading && !text && <div style={{ color: 'var(--err-text)', fontSize: 13 }}>Prompt text unavailable</div>}
          {text && (
            <pre style={{
              fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.7,
              color: 'var(--doc-text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
            }}>
              {text}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Traceability Panel — LLM Call block ──────────────────────────────────

function LlmCallBlock({ queryId }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);

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
              <span className="k">prompt version</span>
              <span className="v">
                {trace.system_prompt_version
                  ? <button className="g2v2-prompt-link" onClick={() => setPromptOpen(true)}>{trace.system_prompt_version} ↗</button>
                  : '—'}
              </span>
              <span className="k">chunks in context</span><span className="v">
                {trace.chunks_sent_to_context != null ? trace.chunks_sent_to_context : '—'}
              </span>
            </div>
          )}
        </div>
      )}
      {promptOpen && trace?.system_prompt_version && (
        <PromptModal version={trace.system_prompt_version} onClose={() => setPromptOpen(false)} />
      )}
    </div>
  );
}

// ── Traceability Panel — Chunk card ──────────────────────────────────────

function ChunkCard({ chunk, highlighted, onViewSource, dimText = false }) {
  const [showMore, setShowMore] = useState(false);
  const [ingOpen, setIngOpen] = useState(false);
  const [prov, setProv] = useState(null);
  const text = chunk.chunk_text || '';
  const isLong = text.length > 300;

  useEffect(() => {
    if (highlighted) setShowMore(false);
  }, [highlighted]);

  const handleIngToggle = () => {
    const next = !ingOpen;
    setIngOpen(next);
    if (next && !prov && chunk.document_id) {
      getChunkProvenance(chunk.document_id)
        .then((d) => setProv(d))
        .catch(() => setProv({}));
    }
  };

  // Merge: fetched provenance wins over stale fields on the chunk object
  const p = { ...chunk, ...prov };

  const agency = chunk.issuing_body || chunk.agency || '—';
  const d = (v) => (v != null && v !== '') ? v : '—';
  const srcLabel = INGESTION_SOURCE_LABELS[p.ingestion_source] || p.ingestion_source || '—';
  const chunkSize = text.length;
  const chunkOf = p.chunk_count != null
    ? `${(chunk.chunk_index ?? 0) + 1} of ${p.chunk_count}`
    : (chunk.chunk_index != null ? String((chunk.chunk_index ?? 0) + 1) : '—');
  const charOffset = (chunk.char_offset_start != null && chunk.char_offset_end != null)
    ? `${chunk.char_offset_start}–${chunk.char_offset_end}`
    : '—';

  return (
    <div
      className={`g2v2-chunk${highlighted ? ' pulse' : ''}`}
      data-testid={`chunk-card-${chunk.chunk_id}`}
    >
      <div className="ch-top">
        {chunk.index != null && <span className="ch-badge">{chunk.index}</span>}
        <span className="ch-title">{chunk.document_title || chunk.document_id || '—'}</span>
        <span className="ch-agency">{agency}</span>
      </div>
      <div className="ch-meta">
        <span><span className="k">clause</span> <span className="v">{chunk.clause_id || '—'}</span></span>
        <span><span className="k">page</span> <span className="v">{chunk.page_no != null ? chunk.page_no + 1 : '—'}</span></span>
        <span><span className="k">type</span> <span className="v">{DOCTYPE_LABEL[chunk.doc_type] || chunk.doc_type || '—'}</span></span>
        <span><span className="k">published</span> <span className="v">{formatDate(chunk.publication_date) || '—'}</span></span>
        {chunk.score != null && (
          <span><span className="k">score</span> <span className="v">{chunk.score.toFixed(4)}</span></span>
        )}
      </div>
      <div className="ch-text" style={dimText ? { color: 'var(--doc-text-2)' } : undefined}>
        {isLong && !showMore ? text.slice(0, 300) + '… ' : text}
        {isLong && (
          <span className="ch-showmore" onClick={() => setShowMore((v) => !v)}>
            {showMore ? 'Show less' : 'Show more'}
          </span>
        )}
      </div>

      {/* Ingestion record — collapsible, lazy-fetched */}
      <div className="ch-ing-wrap">
        <div className="ch-ing-head" onClick={handleIngToggle}>
          <span className="ch-ing-lbl">INGESTION RECORD</span>
          <span className={`chev-sm${ingOpen ? ' open' : ''}`}><ChevRightIcon /></span>
        </div>
        {ingOpen && (
          <div className="g2v2-llm-grid" style={{ marginTop: 6 }}>
            <span className="k">ingested at</span><span className="v">{p.ingested_at ? formatDateTime(p.ingested_at, true) : '—'}</span>
            <span className="k">source</span><span className="v">{srcLabel}</span>
            <span className="k">run ID</span><span className="v" style={{ fontSize: 10 }}>{d(p.trace_id)}</span>
            <span className="k">span ID</span><span className="v" style={{ fontSize: 10 }}>{d(p.span_id)}</span>
            <span className="k">fetched at</span><span className="v">{p.fetched_at ? formatDateTime(p.fetched_at, true) : '—'}</span>
            <span className="k">parsed at</span><span className="v">{p.parsed_at ? formatDateTime(p.parsed_at, true) : '—'}</span>
            <span className="k">status</span><span className="v">{d(p.ingestion_status)}</span>
            <span className="k">embed model</span><span className="v">{d(p.embedding_model)}</span>
            <span className="k">chunk index</span><span className="v">{chunkOf}</span>
            <span className="k">chunk size</span><span className="v">{chunkSize} chars</span>
            <span className="k">char offset</span><span className="v">{charOffset}</span>
          </div>
        )}
      </div>

      <div className="ch-foot">
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

// ── Traceability Panel — Query Parameters block ───────────────────────────

function QueryParamsBlock({ result }) {
  const [open, setOpen] = useState(false);
  const rp = result?.retrieval_params_applied || {};
  const filters = result?.filters_applied || {};
  const subQueries = result?.sub_queries || [];
  const routing = result?.routing_path || '—';

  const activeFilters = Object.entries(filters)
    .filter(([, v]) => v != null && v !== '' && !v.toString().startsWith('_'))
    .map(([k, v]) => `${k}: ${v}`);

  const summary = `${subQueries.length} variation${subQueries.length !== 1 ? 's' : ''} · top_k ${rp.top_k ?? '—'} · ${routing}`;

  return (
    <div className="g2v2-block" data-testid="query-params-block">
      <div className="g2v2-block-head" onClick={() => setOpen((v) => !v)}>
        <span className="lhs">
          <span className={`chev${open ? ' open' : ''}`}><ChevRightIcon /></span>
          <span className="name">Query Parameters</span>
        </span>
        {!open && <span className="summary">{summary}</span>}
      </div>
      {open && (
        <div className="g2v2-block-body">
          <div className="g2v2-llm-grid">
            <span className="k">original query</span>
            <span className="v" style={{ whiteSpace: 'normal', lineHeight: 1.5 }}>{result?.query_text || '—'}</span>
            <span className="k">routing</span><span className="v">{routing}</span>
            <span className="k">top_k</span><span className="v">{rp.top_k ?? '—'}</span>
            <span className="k">score threshold</span><span className="v">{rp.score_threshold ?? '—'}</span>
            <span className="k">query depth</span><span className="v">{rp.query_depth ?? '—'}</span>
            <span className="k">filters</span>
            <span className="v">{activeFilters.length > 0 ? activeFilters.join(' · ') : 'none'}</span>
          </div>
          {subQueries.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--doc-text-3)', letterSpacing: '0.06em', marginBottom: 6 }}>
                EXPANDED VARIATIONS
              </div>
              {subQueries.map((q, i) => (
                <div key={i} style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)', padding: '3px 0', borderBottom: '1px solid var(--doc-border)' }}>
                  <span style={{ color: 'var(--doc-text-3)', marginRight: 6 }}>{i + 1}.</span>{q}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Traceability Panel ────────────────────────────────────────────────────

function TraceabilityPanel({ queryId, result, citations, selectedChunkId, onChunkSelect, onClose, onViewSource }) {
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

        {/* Query Parameters */}
        <QueryParamsBlock result={result} />

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
              <div style={{ borderTop: '1px solid var(--doc-border)', paddingTop: 4 }}>
                {uncited.map((u) => (
                  <ChunkCard
                    key={u.chunk_id}
                    chunk={{ ...u, index: null }}
                    highlighted={false}
                    onViewSource={onViewSource}
                    dimText
                  />
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
  const modalRef = useRef(null);
  const [imgSrc, setImgSrc] = useState(null);
  const [pageNo, setPageNo] = useState(chunk?.page_no ?? 0);
  const [zoom, setZoom] = useState(100);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [pageInput, setPageInput] = useState(String((chunk?.page_no ?? 0) + 1));

  useEffect(() => {
    if (chunk?.source_local_path) {
      setImgSrc(getPdfPage(chunk.source_local_path, pageNo));
    } else {
      setImgSrc(null);
    }
    setPageInput(String(pageNo + 1));
  }, [chunk?.source_local_path, pageNo]);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  function toggleFullscreen() {
    if (!isFullscreen) {
      modalRef.current?.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  }

  function navigatePage(raw) {
    const n = parseInt(raw, 10);
    if (!isNaN(n) && n >= 1) {
      setPageNo(n - 1);
    } else {
      setPageInput(String(pageNo + 1));
    }
  }

  return (
    <div className="g2-pdf-modal" data-testid="pdf-modal" onClick={onClose}>
      <div className="g2-pdf-box" ref={modalRef} onClick={(e) => e.stopPropagation()}>
        <div className="g2-pdf-bar">
          <span className="t">{chunk?.document_title || 'Source Document'}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>Page</span>
            <input
              className="g2-pdf-page-input"
              value={pageInput}
              onChange={(e) => setPageInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') navigatePage(pageInput); }}
              onBlur={() => navigatePage(pageInput)}
            />
            <button className="close" title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'} onClick={toggleFullscreen}>
              {isFullscreen ? <MinimizeIcon /> : <MaximizeIcon />}
            </button>
            <button className="close" onClick={onClose}><CloseIcon /></button>
          </div>
        </div>
        <div className="g2-pdf-stage">
          {imgSrc ? (
            <img src={imgSrc} alt={`Page ${pageNo + 1}`} style={{ width: `${zoom}%` }} onError={() => setImgSrc(null)} />
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
          <div className="g2-pdf-footer">
            <button className="g2-pdf-nav" onClick={() => setPageNo((p) => Math.max(0, p - 1))} disabled={pageNo <= 0}>‹</button>
            <button className="g2-pdf-nav" onClick={() => setPageNo((p) => p + 1)}>›</button>
            <div className="g2-pdf-zoom">
              <button className="g2-pdf-zoom-btn" onClick={() => setZoom((z) => Math.max(25, z - 25))}>−</button>
              <span className="g2-pdf-zoom-lbl">{zoom}%</span>
              <button className="g2-pdf-zoom-btn" onClick={() => setZoom((z) => Math.min(300, z + 25))}>+</button>
            </div>
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
  const { loaded: modelLoaded, checked: modelChecked } = useContext(ModelStatusContext);

  const [filters, setFilters] = useState({});
  const [retrieval, setRetrieval] = useState({ DEFAULT_RETRIEVAL.depth, topK: DEFAULT_RETRIEVAL.topK, scoreThreshold: DEFAULT_RETRIEVAL.scoreThreshold });

  const [queryState, setQueryState] = useState(QUERY_STATES.IDLE);
  const [selectedChunkId, setSelectedChunkId] = useState(null);
  const [pdfChunk, setPdfChunk] = useState(null);
  const [showFormatMenu, setShowFormatMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });
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
      a.href = url; a.download = `ownedpulse-export-${result.query_id}.${fmt}`; a.click();
      URL.revokeObjectURL(url);
    } catch (_) {}
  }, [result?.query_id]);

  const isLanding = !result && !loading && !error;
  const panelOpen = queryState === QUERY_STATES.TRACEABILITY;
  const routingPath = result?.routing_path;
  const isMetadata = routingPath === 'METADATA';

  const { nodes: answerNodes, legalNote: answerLegalNote } = result
    ? renderAnswer(result.answer, selectedChunkId, citations, handleCitationClick)
    : { nodes: null, legalNote: null };

  if (isLanding) {
    return (
      <div className="rp-main-page landing">
        <div className="rp-content-inner">
          <div className="container">
            <div className="rp-query-area">
              <div className="rp-query-bar">
                <QueryInput value={queryText} onSubmit={handleSubmit} disabled={false} />
              </div>
              <FilterBar filters={filters} onChange={setFilters} retrieval={retrieval} onRetrievalChange={setRetrieval} />
              {modelChecked && !modelLoaded && (
                <div style={{ marginTop: 8, padding: '7px 12px', borderRadius: 5, background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)', fontSize: 12, color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 7 }}>
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}><path d="M8 2L1.5 13.5h13z"/><path d="M8 6.5v3.5"/><circle cx="8" cy="11.6" r="0.5" fill="currentColor" stroke="none"/></svg>
                  LLM model is loading — first query may take longer than usual
                </div>
              )}
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
            </div>

            {/* Filter bar below query */}
            <div style={{ marginTop: 6, marginBottom: modelChecked && !modelLoaded ? 12 : 32 }}>
              <FilterBar filters={filters} onChange={setFilters} retrieval={retrieval} onRetrievalChange={setRetrieval} />
              {modelChecked && !modelLoaded && (
                <div style={{ marginTop: 8, marginBottom: 20, padding: '7px 12px', borderRadius: 5, background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)', fontSize: 12, color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 7 }}>
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}><path d="M8 2L1.5 13.5h13z"/><path d="M8 6.5v3.5"/><circle cx="8" cy="11.6" r="0.5" fill="currentColor" stroke="none"/></svg>
                  LLM model is loading — first query may take longer than usual
                </div>
              )}
            </div>

            {/* Answer body */}
            {loading && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
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
                {answerNodes}
                <p className="g2v2-disc">
                  AI-generated answer based on retrieved regulatory documents. Verify critical requirements against current source documents before relying on this response for compliance decisions.
                  {answerLegalNote && <>{' '}{answerLegalNote}</>}
                </p>

                {/* Export button — flush left, above query expansion */}
                <div style={{ marginTop: 14, marginBottom: 4 }}>
                  <button
                    className="g2-export"
                    ref={chevRef}
                    onClick={() => {
                      if (chevRef.current) {
                        const r = chevRef.current.getBoundingClientRect();
                        setMenuPos({ top: r.bottom + 4, left: r.left });
                      }
                      setShowFormatMenu((m) => !m);
                    }}
                  >
                    <DownloadIcon /> Export
                  </button>
                </div>
                <QueryExpansion subQueries={result.sub_queries} />

                {/* Consolidated footer — left: id · time · routing · chunks, right: traceability */}
                <div className="g2v2-routing-footer">
                  <span className="g2v2-routing-label">
                    q-{result.query_id?.slice(0, 8)} · {formatDateTime(result.timestamp, true)} · {routingPath} · {citations.length} chunk{citations.length !== 1 ? 's' : ''} retrieved
                  </span>
                  {!panelOpen && !isMetadata && citations.length > 0 && (
                    <button
                      className="g2v2-trace-btn"
                      data-testid="query-traceability-btn"
                      onClick={handleOpenPanel}
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                      View traceability →
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Traceability panel */}
      {panelOpen && (
        <TraceabilityPanel
          queryId={result?.query_id}
          result={{ ...result, query_text: queryText }}
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
            position: 'fixed', top: menuPos.top, left: menuPos.left,
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
