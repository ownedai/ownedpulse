import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import Tooltip from '../common/Tooltip';
import { getPdfPage, getPdfInfo, getTrace } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

const AGENCY_TIPS = {
  FDA: 'U.S. Food & Drug Administration',
  EMA: 'European Medicines Agency',
  ICH: 'International Council for Harmonisation',
};

const PREVIEW_LEN = 200;

/* ── Trace helpers ───────────────────────────────────────────────────────── */

function ExpandableValue({ value }) {
  const [expanded, setExpanded] = useState(false);
  if (!value || value.length <= PREVIEW_LEN) return <span className="v">{value}</span>;
  return (
    <span className="v">
      {expanded ? value : value.slice(0, PREVIEW_LEN) + '…'}
      {' '}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent-d)', fontSize: 11, padding: 0 }}
      >
        {expanded ? 'show less' : 'show more'}
      </button>
    </span>
  );
}

function TraceStep({ number, name, latency, children }) {
  const [open, setOpen] = useState(number <= 2);
  return (
    <div className={`rp-trace-step${open ? ' open' : ''}`}>
      <div className="rp-trace-step-head" onClick={() => setOpen((v) => !v)}>
        <span className="name"><span className="ord">{number}</span>{name}</span>
        <span className="latency">
          {latency}
          <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d={open ? 'M3 7.5l3-3 3 3' : 'M3 4.5l3 3 3-3'} />
          </svg>
        </span>
      </div>
      {open && <div className="rp-trace-step-body">{children}</div>}
    </div>
  );
}

function TraceRow({ label, value }) {
  return (
    <div className="rp-trace-row">
      <span className="k">{label}</span>
      <span className="v">{value}</span>
    </div>
  );
}

function TraceTab({ traceId }) {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!traceId) return;
    setLoading(true);
    setError(null);
    setTrace(null);
    getTrace(traceId)
      .then(setTrace)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [traceId]);

  if (!traceId) return <div className="rp-drawer-empty">No trace available for this query.</div>;

  return (
    <div className="rp-trace-content">
      {trace && (
        <div className="rp-trace-meta">
          <span className="k">Trace ID</span>
          <span className="v" style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{traceId}</span>
          {trace.latency && <> · <span className="v">{trace.latency.toFixed(0)} ms total</span></>}
          {trace.observations && <> · <span className="v">{trace.observations.length} steps</span></>}
        </div>
      )}
      {loading && <div className="rp-drawer-empty">Loading trace…</div>}
      {error && <div className="rp-drawer-empty" style={{ color: 'var(--err-text)' }}>Failed to load: {error}</div>}
      {trace?.observations?.map((obs, i) => (
        <TraceStep
          key={i}
          number={i + 1}
          name={obs.name || obs.type || `Step ${i + 1}`}
          latency={obs.latency ? `${obs.latency.toFixed(0)} ms` : '—'}
        >
          {obs.model && <TraceRow label="model" value={obs.model} />}
          {obs.input && (
            <div className="rp-trace-row">
              <span className="k">input</span>
              <ExpandableValue value={typeof obs.input === 'string' ? obs.input : JSON.stringify(obs.input)} />
            </div>
          )}
          {obs.output && (
            <div className="rp-trace-row">
              <span className="k">output</span>
              <ExpandableValue value={typeof obs.output === 'string' ? obs.output : JSON.stringify(obs.output)} />
            </div>
          )}
          {obs.usage && (obs.usage.promptTokens || obs.usage.completionTokens) && (
            <TraceRow label="tokens" value={`${obs.usage.promptTokens || 0} prompt + ${obs.usage.completionTokens || 0} completion`} />
          )}
        </TraceStep>
      ))}
      {trace && (!trace.observations || trace.observations.length === 0) && (
        <div className="rp-drawer-empty">No observation data for this trace.</div>
      )}
    </div>
  );
}

/* ── Chunk tab ───────────────────────────────────────────────────────────── */

function ChunkTab({ citation }) {
  const { chunk_text, char_offset_start, char_offset_end } = citation;
  return (
    <div style={{ padding: '18px 20px 24px' }}>
      <div className="rp-section-lbl" style={{ marginBottom: 6 }}>Retrieved chunk</div>
      <div className="rp-chunk-head">
        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
          chars {char_offset_start || 0}–{char_offset_end || chunk_text?.length || 0}
        </span>
      </div>
      <div className="rp-chunk">{chunk_text}</div>
    </div>
  );
}

/* ── Provenance tab ──────────────────────────────────────────────────────── */

function ProvenanceTab({ citation }) {
  const [pdfPage, setPdfPage] = useState(citation?.page_no ?? null);
  const [pdfError, setPdfError] = useState(false);
  const [totalPages, setTotalPages] = useState(null);

  useEffect(() => {
    setPdfPage(citation?.page_no ?? null);
    setPdfError(false);
    setTotalPages(null);
    if (citation?.source_local_path) {
      getPdfInfo(citation.source_local_path)
        .then((info) => setTotalPages(info.page_count))
        .catch(() => {});
    }
  }, [citation?.chunk_id]);

  const {
    document_title, issuing_body, document_version, superseded,
    clause_id, publication_date, chunk_index,
    char_offset_start, char_offset_end, chunk_text,
    chunked_at, source_url, source_local_path, source_file_format,
  } = citation;

  const agency = issuing_body === 'EU-Commission' ? 'EMA' : (issuing_body || 'Unknown');
  const isHtml = source_file_format === 'html' || !source_local_path;
  const fileName = source_local_path ? source_local_path.split('/').pop() : null;
  const pdfUrl = source_local_path && pdfPage != null ? getPdfPage(source_local_path, pdfPage) : null;

  return (
    <div style={{ padding: '18px 20px 24px' }}>
      <div className="rp-section-lbl" style={{ marginBottom: 8 }}>Provenance</div>
      <div className="rp-prov">
        <div className="row">
          <span className="k">Source file</span>
          <span className="v">
            {fileName ? (
              <Tooltip tip={source_local_path}><span style={{ cursor: 'help' }}>{fileName}</span></Tooltip>
            ) : <span className="muted">Not available</span>}
          </span>
        </div>
        <div className="row">
          <span className="k">Document version</span>
          <span className="v">{document_version || '—'}</span>
        </div>
        <div className="row">
          <span className="k">Clause ID</span>
          <span className="v">{clause_id || 'Not available'}</span>
        </div>
        <div className="row">
          <span className="k">Publication date</span>
          <span className="v">{publication_date ? formatDate(publication_date) : 'Not available'}</span>
        </div>
        <div className="row">
          <span className="k">Agency</span>
          <span className="v">{agency}</span>
        </div>
        <div className="row">
          <span className="k">Chunk index</span>
          <span className="v">{chunk_index != null ? chunk_index : '—'}</span>
        </div>
        <div className="row">
          <span className="k">Character offsets</span>
          <span className="v">chars {char_offset_start || 0}–{char_offset_end || chunk_text?.length || 0}</span>
        </div>
        <div className="row">
          <span className="k">Ingestion date</span>
          <span className="v">{chunked_at ? formatDateTime(chunked_at) : 'Not available'}</span>
        </div>
        <div className="row">
          <span className="k">Source URL</span>
          <span className="v">
            {source_url
              ? <a href={source_url} target="_blank" rel="noopener noreferrer">{source_url}</a>
              : <span className="muted">Not available</span>}
          </span>
        </div>
      </div>

      {isHtml ? (
        <>
          <div className="rp-section-lbl" style={{ marginBottom: 8 }}>Source</div>
          <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--doc-text-2)', lineHeight: 1.5 }}>
            This document is an HTML source. Use the link below to open the original page.
          </p>
          {source_url ? (
            <button className="action" onClick={() => window.open(source_url, '_blank', 'noopener,noreferrer')}>
              Open source page ↗
            </button>
          ) : (
            <div className="rp-nopdf">No source URL available</div>
          )}
        </>
      ) : (
        <>
          <div className="rp-section-lbl" style={{ marginBottom: 8 }}>PDF page</div>
          {source_local_path ? (
            <div className="rp-pdf">
              <div className="head">
                <span>Page {pdfPage != null ? pdfPage + 1 : '—'}{totalPages ? ` of ${totalPages}` : ''}</span>
                <div className="pager">
                  <button onClick={() => { setPdfPage((p) => Math.max(0, (p || 0) - 1)); setPdfError(false); }} disabled={!pdfPage || pdfPage <= 0}>&larr;</button>
                  <span>{pdfPage != null ? pdfPage + 1 : '—'}</span>
                  <button onClick={() => { setPdfPage((p) => (p || 0) + 1); setPdfError(false); }} disabled={totalPages !== null && (pdfPage || 0) + 1 >= totalPages}>&rarr;</button>
                </div>
              </div>
              {pdfUrl && !pdfError ? (
                <img
                  src={pdfUrl}
                  alt={`PDF page ${(pdfPage || 0) + 1}`}
                  style={{ width: '100%', height: 'auto', border: '1px solid var(--doc-border)', borderRadius: 3 }}
                  onError={() => setPdfError(true)}
                />
              ) : (
                <div className="rp-nopdf">PDF not available</div>
              )}
            </div>
          ) : (
            <div className="rp-nopdf">PDF not available</div>
          )}
        </>
      )}
    </div>
  );
}

/* ── Main overlay drawer ─────────────────────────────────────────────────── */

function truncate(str, max) {
  if (!str) return '—';
  return str.length > max ? str.slice(0, max - 1) + '…' : str;
}

export default function SourcePanel({
  citation,
  traceId,
  initialTab = 'chunk',
  onClose,
  onPrevChunk,
  onNextChunk,
  hasPrev,
  hasNext,
}) {
  const [activeTab, setActiveTab] = useState(initialTab);

  // Reset tab when citation or initialTab changes
  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab, citation?.index]);

  if (!citation && !traceId) return null;

  const hasCitation = !!citation;
  const hasTrace = !!traceId;

  const tabs = [
    ...(hasCitation ? [{ id: 'chunk', label: 'Chunk' }, { id: 'provenance', label: 'Provenance' }] : []),
    ...(hasTrace ? [{ id: 'trace', label: 'Trace' }] : []),
  ];

  const agency = citation
    ? (citation.issuing_body === 'EU-Commission' ? 'EMA' : (citation.issuing_body || 'Unknown'))
    : null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div className="rp-overlay-backdrop" onClick={onClose} />

      {/* Drawer */}
      <aside className="rp-overlay-drawer">
        {/* Header */}
        <div className="rp-source-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="lbl">
              {hasCitation ? `Source · citation [${citation.index}]` : 'Pipeline trace'}
            </div>
            {hasCitation && (
              <>
                <Tooltip tip={citation.document_title?.length > 80 ? citation.document_title : undefined}>
                  <h3>{truncate(citation.document_title, 80)}</h3>
                </Tooltip>
                <div className="sub">
                  <Tooltip tip={AGENCY_TIPS[agency] || agency}>
                    <span className="v" style={{ cursor: 'help' }}>{agency}</span>
                  </Tooltip>
                  {' · '}
                  <span className="v">{citation.document_version || '—'}</span>
                  {' · '}
                  <span className="v">{citation.superseded ? 'Superseded' : 'Current'}</span>
                </div>
              </>
            )}
          </div>
          <div className="actions">
            <button className="ico-btn" onClick={onClose} aria-label="Close">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M1 1l10 10M1 11L11 1" />
              </svg>
            </button>
          </div>
        </div>

        {/* Chunk navigation — only for Chunk/Provenance tabs */}
        {hasCitation && activeTab !== 'trace' && (
          <div className="rp-source-nav">
            <button
              className={!hasPrev ? 'disabled' : ''}
              disabled={!hasPrev}
              onClick={() => { onPrevChunk?.(); }}
            >
              &larr; Previous chunk
            </button>
            <button
              className={`next${!hasNext ? ' disabled' : ''}`}
              disabled={!hasNext}
              onClick={() => { onNextChunk?.(); }}
            >
              Next chunk &rarr;
            </button>
          </div>
        )}

        {/* Tab bar */}
        {tabs.length > 1 && (
          <div className="rp-drawer-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`rp-drawer-tab${activeTab === tab.id ? ' active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Tab content */}
        <div className="rp-drawer-scroll">
          {activeTab === 'chunk' && hasCitation && <ChunkTab citation={citation} />}
          {activeTab === 'provenance' && hasCitation && <ProvenanceTab citation={citation} />}
          {activeTab === 'trace' && <TraceTab traceId={traceId} />}
        </div>
      </aside>
    </>,
    document.body
  );
}
