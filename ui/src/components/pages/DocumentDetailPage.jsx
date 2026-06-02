import { useState, useEffect } from 'react';
import { useParams, Link, useLocation } from 'react-router-dom';
import { getDocumentDetail, getDocumentChunks, getSupersedeChain } from '../../api/client';
import Tooltip from '../common/Tooltip';
import { formatDate, formatDateTime } from '../../dateFormat';
import { getStatusConfig } from '../../utils/status';

function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em',
      textTransform: 'uppercase', color: 'var(--accent-l)', fontWeight: 600,
      marginBottom: 10, marginTop: 24,
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

function hashAbbr(h) {
  if (!h) return '—';
  return h.length > 20 ? h.substring(0, 20) + '…' : h;
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

      <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: '-0.015em', margin: '8px 0 4px', color: 'var(--doc-text)', lineHeight: 1.3 }}>
        {doc.document_title}
      </h1>
      <p style={{ fontSize: 13, color: 'var(--doc-text-2)', margin: '0 0 24px' }}>
        {doc.issuing_body} · {(doc.document_type || doc.doc_type || '').replace(/-/g, ' ')} · {doc.document_version || 'v1'}
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
          <MetaRow label="Version">{doc.document_version || '—'}</MetaRow>
          <MetaRow label="Publication Date">{formatDate(doc.publication_date)}</MetaRow>
          <MetaRow label="Status"><StatusBadge status={doc.ingestion_status} /></MetaRow>
          <MetaRow label="Feed">{doc.feed_id || (doc.corpus_doc ? 'Base corpus' : '—')}</MetaRow>
          <MetaRow label="Source URL">
            {doc.source_url ? (
              <a href={doc.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-l)', fontSize: 12 }}>
                View source ↗
              </a>
            ) : '—'}
          </MetaRow>
          <MetaRow label="Run ID">
            {doc.run_id ? (
              <Link to={`/corpus/runs?run=${doc.run_id}`} style={{ color: 'var(--accent-l)', fontFamily: 'var(--mono)', fontSize: 11 }}>
                {doc.run_id.substring(0, 12)}…
              </Link>
            ) : '—'}
          </MetaRow>

          <SectionLabel>Source Integrity</SectionLabel>
          <div style={{ fontSize: 13 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--doc-border)', gap: 16 }}>
              <Tooltip tip="SHA-256 of the source file recorded at ingestion time (document registry)">
                <span style={{ color: 'var(--doc-text-2)', cursor: 'help' }}>Ingestion hash</span>
              </Tooltip>
              <Tooltip tip={doc.pg_source_hash || 'Not recorded'}>
                <code style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{hashAbbr(doc.pg_source_hash)}</code>
              </Tooltip>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--doc-border)', gap: 16 }}>
              <Tooltip tip="SHA-256 stored in the vector index alongside chunk embeddings">
                <span style={{ color: 'var(--doc-text-2)', cursor: 'help' }}>Vector store hash</span>
              </Tooltip>
              <Tooltip tip={doc.qdrant_source_hash || 'Not recorded'}>
                <code style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{hashAbbr(doc.qdrant_source_hash)}</code>
              </Tooltip>
            </div>
            <div style={{ marginTop: 10 }}>
              {doc.hash_match ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--ok-text)', fontSize: 12, background: 'var(--ok-tint)', border: '1px solid var(--ok-tint-border)', padding: '4px 10px', borderRadius: 4 }}>
                  <span style={{ fontSize: 16 }}>✓</span> Hashes match
                </span>
              ) : (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--err-text)', fontSize: 12, background: 'var(--err-tint)', border: '1px solid var(--err-tint-border)', padding: '4px 10px', borderRadius: 4 }}>
                  ✗ Hash mismatch — investigate
                </span>
              )}
            </div>
          </div>

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
                  <th style={{ width: 50 }}>#</th>
                  <th>Clause ID</th>
                  <th style={{ width: 80 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {chunks.items.map((ch) => (
                  <>
                    <tr
                      key={ch.chunk_id}
                      onClick={() => setExpandedChunk(expandedChunk === ch.chunk_id ? null : ch.chunk_id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="mono">{ch.chunk_index}</td>
                      <td className="mono" style={{ fontSize: 11 }}>{ch.clause_id || '—'}</td>
                      <td>
                        <span className={`status ${ch.chunk_status === 'active' ? 'ok' : 'warn'}`}>
                          {ch.chunk_status}
                        </span>
                      </td>
                    </tr>
                    {expandedChunk === ch.chunk_id && (
                      <tr key={`${ch.chunk_id}-exp`}>
                        <td colSpan={3} style={{ padding: '10px 12px', background: 'var(--doc-bg)' }}>
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
                  </>
                ))}
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
    </div>
  );
}
