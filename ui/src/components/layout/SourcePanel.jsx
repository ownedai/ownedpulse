import { useState } from 'react';
import Tooltip from '../common/Tooltip';
import { getPdfPage } from '../../api/client';
import { formatDate, formatDateTime } from '../../dateFormat';

const AGENCY_SOURCE_TIPS = {
  FDA: 'U.S. Food & Drug Administration',
  EMA: 'European Medicines Agency',
  ICH: 'International Council for Harmonisation',
};

export default function SourcePanel({ citation, onClose, onPrevChunk, onNextChunk, hasPrev, hasNext }) {
  const [pdfPage, setPdfPage] = useState(citation?.page_no ?? null);
  const [pdfError, setPdfError] = useState(false);

  if (!citation) return null;

  const {
    document_title,
    issuing_body,
    document_version,
    superseded,
    clause_id,
    publication_date,
    chunk_text,
    chunk_index,
    char_offset_start,
    char_offset_end,
    chunked_at,
    source_url,
    source_local_path,
    page_no,
  } = citation;

  const agency = issuing_body === 'EU-Commission' ? 'EMA' : (issuing_body || 'Unknown');
  const version = document_version || '—';
  const clause = clause_id || 'Not available';
  const pubDate = publication_date
    ? formatDate(publication_date)
    : 'Not available';
  const ingestDate = chunked_at
    ? formatDateTime(chunked_at)
    : 'Not available';
  const fileName = source_local_path
    ? source_local_path.split('/').pop()
    : null;

  // Truncate title for display
  const displayTitle = document_title && document_title.length > 80
    ? document_title.slice(0, 77) + '...'
    : document_title;

  const pdfUrl = source_local_path && pdfPage != null
    ? getPdfPage(source_local_path, pdfPage)
    : null;

  return (
    <aside className="rp-source">
      {/* Header */}
      <div className="rp-source-head">
        <div>
          <div className="lbl">Source · citation [{citation.index}]</div>
          <Tooltip tip={document_title && document_title.length > 80 ? document_title : undefined}>
            <h3>{displayTitle}</h3>
          </Tooltip>
          <div className="sub">
            <Tooltip tip={AGENCY_SOURCE_TIPS[agency] || agency}>
              <span className="v" style={{ cursor: 'help' }}>{agency}</span>
            </Tooltip>
            {' · '}
            <span className="v">{version}</span>
            {' · '}
            <span className="v">{superseded ? 'Superseded' : 'Current'}</span>
          </div>
        </div>
        <div className="actions">
          <button className="ico-btn" onClick={onClose} aria-label="Close source panel">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M1 1l10 10M1 11L11 1" />
            </svg>
          </button>
        </div>
      </div>

      {/* Chunk navigation */}
      <div className="rp-source-nav">
        <button
          className={!hasPrev ? 'disabled' : ''}
          onClick={() => { onPrevChunk?.(); setPdfPage(citation.page_no); setPdfError(false); }}
          disabled={!hasPrev}
        >
          &larr; Previous chunk
        </button>
        <button
          className={`next${!hasNext ? ' disabled' : ''}`}
          onClick={() => { onNextChunk?.(); setPdfPage(citation.page_no); setPdfError(false); }}
          disabled={!hasNext}
        >
          Next chunk &rarr;
        </button>
      </div>

      <div className="rp-source-scroll">
        {/* Retrieved chunk */}
        <div className="rp-section-lbl">Retrieved chunk</div>
        <div className="rp-chunk-head" style={{ marginTop: 8 }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>
            chars {char_offset_start || 0}-{char_offset_end || chunk_text?.length || 0}
          </span>
        </div>
        <div className="rp-chunk">{chunk_text}</div>

        {/* Provenance metadata */}
        <div className="rp-section-lbl" style={{ marginBottom: 8 }}>Provenance</div>
        <div className="rp-prov">
          <div className="row">
            <span className="k">Source file</span>
            <span className="v">
              {fileName ? (
                <Tooltip tip={source_local_path}>
                  <span style={{ cursor: 'help' }}>{fileName}</span>
                </Tooltip>
              ) : (
                <span className="muted">Not available</span>
              )}
            </span>
          </div>
          <div className="row">
            <span className="k">Document version</span>
            <span className="v">{version}</span>
          </div>
          <div className="row">
            <span className="k">Clause ID</span>
            <span className="v">{clause}</span>
          </div>
          <div className="row">
            <span className="k">Publication date</span>
            <span className="v">{pubDate}</span>
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
            <span className="v">chars {char_offset_start || 0}-{char_offset_end || chunk_text?.length || 0}</span>
          </div>
          <div className="row">
            <span className="k">Ingestion date</span>
            <span className="v">{ingestDate}</span>
          </div>
          <div className="row">
            <span className="k">Source URL</span>
            <span className="v">
              {source_url ? (
                <a href={source_url} target="_blank" rel="noopener noreferrer">{source_url}</a>
              ) : (
                <span className="muted">Not available</span>
              )}
            </span>
          </div>
        </div>

        {/* PDF page */}
        <div className="rp-section-lbl" style={{ marginBottom: 8 }}>PDF page</div>
        {source_local_path ? (
          <div className="rp-pdf">
            <div className="head">
              <span>Page {pdfPage != null ? pdfPage + 1 : '—'}</span>
              <div className="pager">
                <button onClick={() => setPdfPage((p) => Math.max(0, (p || 0) - 1))} disabled={!pdfPage || pdfPage <= 0}>
                  &larr;
                </button>
                <span>{pdfPage != null ? pdfPage + 1 : '—'}</span>
                <button onClick={() => setPdfPage((p) => (p || 0) + 1)}>
                  &rarr;
                </button>
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
      </div>
    </aside>
  );
}
