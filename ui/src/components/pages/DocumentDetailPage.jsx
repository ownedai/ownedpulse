import React, { useState, useEffect, useRef } from 'react';
import { useParams, Link, useLocation } from 'react-router-dom';
import { getDocumentDetail, getDocumentChunks, getSupersedeChain, getPdfPage } from '../../api/client';
import Tooltip from '../common/Tooltip';
import { formatDate, formatDateTime, isFutureDate } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';

function CloseIcon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>;
}
function MaximizeIcon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>;
}
function MinimizeIcon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 14 10 14 10 20"/><polyline points="20 4 14 4 14 10"/><line x1="10" y1="14" x2="3" y2="21"/><line x1="21" y1="3" x2="14" y2="10"/></svg>;
}
function ExtIcon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>;
}

function PdfModal({ doc, onClose }) {
  const modalRef = useRef(null);
  const [pageNo, setPageNo] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [pageInput, setPageInput] = useState('1');
  const [imgSrc, setImgSrc] = useState(null);

  useEffect(() => {
    if (doc?.source_local_path) {
      setImgSrc(getPdfPage(doc.source_local_path, pageNo));
    }
    setPageInput(String(pageNo + 1));
  }, [doc?.source_local_path, pageNo]);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  function toggleFullscreen() {
    if (!isFullscreen) modalRef.current?.requestFullscreen();
    else document.exitFullscreen();
  }

  function navigatePage(raw) {
    const n = parseInt(raw, 10);
    if (!isNaN(n) && n >= 1) setPageNo(n - 1);
    else setPageInput(String(pageNo + 1));
  }

  return (
    <div className="g2-pdf-modal" data-testid="pdf-modal" onClick={onClose}>
      <div className="g2-pdf-box" ref={modalRef} onClick={(e) => e.stopPropagation()}>
        <div className="g2-pdf-bar">
          <span className="t">{doc?.document_title || 'Source Document'}</span>
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
          ) : doc?.source_url ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--doc-text-2)', fontSize: 13.5 }}>
              <p style={{ marginBottom: 12 }}>PDF preview not available for this document.</p>
              <a href={doc.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-l)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                Open source document <ExtIcon />
              </a>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--doc-text-3)', fontSize: 13.5 }}>PDF not available</div>
          )}
        </div>
        {doc?.source_local_path && (
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

function SectionLabel({ children, style }) {
  return (
    <div style={{
      fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em',
      textTransform: 'uppercase', color: 'var(--accent-l)', fontWeight: 600,
      marginBottom: 10, marginTop: 24, ...style,
    }}>
      {children}
    </div>
  );
}

function MetaRow({ label, children }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '5px 0', borderBottom: '1px solid var(--doc-border)', gap: 16, fontSize: 13 }}>
      <span style={{ color: 'var(--doc-text-2)', flexShrink: 0, minWidth: 120 }}>{label}</span>
      <span style={{ textAlign: 'right', wordBreak: 'break-all' }}>{children}</span>
    </div>
  );
}

function StatusBadge({ status }) {
  const c = getStatusConfig(status);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 600,
      letterSpacing: '0.06em', textTransform: 'uppercase',
      padding: '2px 7px', borderRadius: 3,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: 3, background: c.dot, flexShrink: 0 }} />
      {c.label}
    </span>
  );
}


export default function DocumentDetailPage() {
  const { docId } = useParams();
  const { state: navState } = useLocation();
  const fromSources = navState?.from === 'sources';
  const backTo = fromSources ? '/sources' : '/corpus';
  const backLabel = fromSources ? '← Back to sources' : '← Back to corpus';
  const [doc, setDoc] = useState(null);
  const [chunks, setChunks] = useState({ total: 0, items: [] });
  const [chain, setChain] = useState(null);
  const [loading, setLoading] = useState(true);
  const [chunkPage, setChunkPage] = useState(1);
  const [expandedChunk, setExpandedChunk] = useState(null);
  const [pdfOpen, setPdfOpen] = useState(false);
  const chunkPageSize = 50;

  useEffect(() => {
    if (!docId) return;
    setLoading(true);
    getDocumentDetail(docId)
      .then(setDoc)
      .catch(() => setDoc(null))
      .finally(() => setLoading(false));
  }, [docId]);

  useEffect(() => {
    if (!docId) return;
    getDocumentChunks(docId, chunkPage, chunkPageSize).then(setChunks).catch(() => {});
  }, [docId, chunkPage]);

  useEffect(() => {
    if (doc?.document_family_id) {
      getSupersedeChain(doc.document_family_id).then(setChain).catch(() => {});
    }
  }, [doc?.document_family_id]);


  if (loading) {
    return <div className="rp-page-head"><h1>Document Detail</h1><p>Loading...</p></div>;
  }

  if (!doc) {
    return (
      <div className="rp-page-head">
        <h1>Document Detail</h1>
        <p>Document not found.</p>
        <Link to={backTo} style={{ color: 'var(--accent-l)' }}>{backLabel}</Link>
      </div>
    );
  }

  const totalChunkPages = Math.ceil(chunks.total / chunkPageSize);

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1200 }}>
      <Link to={backTo} style={{ color: 'var(--accent-l)', fontSize: 13, marginBottom: 16, display: 'inline-block' }}>
        {backLabel}
      </Link>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, margin: '8px 0 4px' }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: '-0.015em', margin: 0, color: 'var(--doc-text)', lineHeight: 1.3 }}>
          {doc.document_title}
        </h1>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0, paddingTop: 4 }}>
          {doc.source_local_path && doc.source_file_format === 'pdf' && (
            <button
              onClick={() => setPdfOpen((v) => !v)}
              style={{
                padding: '6px 14px', fontSize: 12.5, borderRadius: 4, cursor: 'pointer',
                background: pdfOpen ? 'var(--accent-l)' : 'transparent',
                color: pdfOpen ? '#fff' : 'var(--accent-l)',
                border: '1px solid var(--accent-l)', fontWeight: 500,
              }}
            >
              {pdfOpen ? 'Hide PDF' : 'View PDF'}
            </button>
          )}
          {doc.source_url && (
            <a
              href={doc.source_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: '6px 14px', fontSize: 12.5, borderRadius: 4,
                background: 'transparent', color: 'var(--doc-text-2)',
                border: '1px solid var(--doc-border)', textDecoration: 'none', fontWeight: 500,
              }}
            >
              Source ↗
            </a>
          )}
        </div>
      </div>
      <p style={{ fontSize: 13, color: 'var(--doc-text-2)', margin: '4px 0 24px' }}>
        {doc.issuing_body} · {(doc.document_type || doc.doc_type || '').replace(/-/g, ' ')} · {doc.document_version && doc.document_version !== '1.0' ? doc.document_version : '—'}
      </p>

      {/* 2-column layout */}
      <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start' }}>
        {/* Left column — 60% */}
        <div style={{ flex: '0 0 60%', minWidth: 0 }}>
          <SectionLabel>Metadata</SectionLabel>
          <MetaRow label="Document ID">
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.document_id}</span>
          </MetaRow>
          <MetaRow label="Issuing Body">{doc.issuing_body}</MetaRow>
          <MetaRow label="Document Type">{(doc.document_type || doc.doc_type || '—').replace(/-/g, ' ')}</MetaRow>
          <MetaRow label="Version">{doc.document_version && doc.document_version !== '1.0' ? doc.document_version : '—'}</MetaRow>
          <MetaRow label="Published">
            {isFutureDate(doc.publication_date) ? (
              <Tooltip tip="Future effective date — this document is not yet in force">
                <span style={{ cursor: 'help', borderBottom: '1px dashed currentColor' }}>{formatDate(doc.publication_date)}</span>
              </Tooltip>
            ) : formatDate(doc.publication_date)}
          </MetaRow>
          <MetaRow label="Status"><StatusBadge status={doc.ingestion_status} /></MetaRow>
          <MetaRow label="Source">{doc.feed_id || (doc.corpus_doc ? 'Base corpus' : '—')}</MetaRow>
          <MetaRow label="Run ID">
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{doc.run_id || '—'}</span>
          </MetaRow>

          <SectionLabel>Source Integrity</SectionLabel>
          <Tooltip tip={
            <span>
              <span style={{ display: 'block', marginBottom: 4 }}>Ingestion: {doc.pg_source_hash || 'Not recorded'}</span>
              <span style={{ display: 'block' }}>Vector store: {doc.qdrant_source_hash || 'Not recorded'}</span>
            </span>
          }>
            {doc.hash_match ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--ok-text)', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', background: 'var(--ok-tint)', border: '1px solid var(--ok-tint-border)', padding: '2px 8px', borderRadius: 3, cursor: 'help' }}>
                ✓ Hashes match
              </span>
            ) : (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--err-text)', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', padding: '2px 8px', borderRadius: 3, cursor: 'help' }}>
                ✗ Mismatch
              </span>
            )}
          </Tooltip>

          {chain && chain.chain && chain.chain.length > 1 && (
            <>
              <SectionLabel>Version Chain</SectionLabel>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                {chain.chain.map((v, i) => (
                  <span key={v.document_id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Link
                      to={`/corpus/${v.document_id}`}
                      style={{
                        padding: '4px 10px', borderRadius: 999,
                        fontSize: 11, fontFamily: 'var(--mono)',
                        textDecoration: 'none',
                        background: v.document_id === docId ? 'var(--accent-l)' : 'transparent',
                        color: v.document_id === docId ? '#fff' : 'var(--doc-text-2)',
                        border: v.document_id === docId ? '1px solid var(--accent-l)' : '1px solid var(--doc-border)',
                        opacity: v.is_superseded && v.document_id !== docId ? 0.6 : 1,
                      }}
                      title={`${v.document_version} · ${formatDate(v.publication_date)}`}
                    >
                      {v.document_version || v.document_id.substring(0, 10)}
                    </Link>
                    {i < chain.chain.length - 1 && <span style={{ color: 'var(--doc-text-3)', fontSize: 12 }}>›</span>}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Right column — 40% */}
        <div style={{ flex: '1 1 0', minWidth: 0 }}>
          <SectionLabel>Chunks ({chunks.total})</SectionLabel>
          <div style={{ overflowX: 'auto' }}>
            <table className="rp-table" style={{ margin: 0 }}>
              <thead>
                <tr>
                  <th style={{ width: 40 }}>#</th>
                  <th style={{ width: 70 }}>Size</th>
                  <th style={{ width: 130 }}>Offset</th>
                  <th>Clause ID</th>
                </tr>
              </thead>
              <tbody>
                {chunks.items.map((ch) => {
                  const size = (ch.char_offset_end != null && ch.char_offset_start != null)
                    ? ch.char_offset_end - ch.char_offset_start
                    : (ch.chunk_text ? ch.chunk_text.length : null);
                  const offset = (ch.char_offset_start != null && ch.char_offset_end != null)
                    ? `${ch.char_offset_start}–${ch.char_offset_end}`
                    : '—';
                  return (
                  <React.Fragment key={ch.chunk_id}>
                    <tr
                      onClick={() => setExpandedChunk(expandedChunk === ch.chunk_id ? null : ch.chunk_id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="mono">{ch.chunk_index}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{size != null ? size.toLocaleString() : '—'}</td>
                      <td className="mono" style={{ fontSize: 10 }}>{offset}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{ch.clause_id || '—'}</td>
                    </tr>
                    {expandedChunk === ch.chunk_id && (
                      <tr>
                        <td colSpan={4} style={{ padding: '10px 12px', background: 'var(--doc-bg)' }}>
                          <pre style={{
                            fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.6,
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            maxHeight: 240, overflowY: 'auto', margin: 0,
                            padding: 10, background: 'var(--doc-surface)',
                            border: '1px solid var(--doc-border)', borderRadius: 4,
                          }}>
                            {ch.chunk_text}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {totalChunkPages > 1 && (
            <div className="rp-pager" style={{ marginTop: 12 }}>
              <span>{((chunkPage - 1) * chunkPageSize) + 1}–{Math.min(chunkPage * chunkPageSize, chunks.total)} of {chunks.total}</span>
              <div className="pages">
                <button onClick={() => setChunkPage(Math.max(1, chunkPage - 1))} disabled={chunkPage <= 1}>&larr;</button>
                <button onClick={() => setChunkPage(chunkPage + 1)} disabled={chunkPage >= totalChunkPages}>&rarr;</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {pdfOpen && (
        <PdfModal doc={doc} onClose={() => setPdfOpen(false)} />
      )}
    </div>
  );
}
