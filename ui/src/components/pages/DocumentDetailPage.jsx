import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getDocumentDetail, getDocumentChunks, getSupersedeChain } from '../../api/client';
import Tooltip from '../common/Tooltip';
import { formatDate } from '../../dateFormat';

function hashAbbr(h) {
  if (!h) return '—';
  return h.length > 16 ? h.substring(0, 16) + '...' : h;
}

export default function DocumentDetailPage() {
  const { docId } = useParams();
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
    getDocumentChunks(docId, chunkPage, chunkPageSize)
      .then(setChunks)
      .catch(() => {});
  }, [docId, chunkPage]);

  useEffect(() => {
    if (doc?.document_family_id) {
      getSupersedeChain(doc.document_family_id)
        .then(setChain)
        .catch(() => {});
    }
  }, [doc?.document_family_id]);

  if (loading) {
    return (
      <div className="rp-page-head">
        <h1>Document Detail</h1>
        <p>Loading...</p>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="rp-page-head">
        <h1>Document Detail</h1>
        <p>Document not found.</p>
        <Link to="/corpus" style={{ color: 'var(--accent-l)' }}>Back to corpus</Link>
      </div>
    );
  }

  const totalChunkPages = Math.ceil(chunks.total / chunkPageSize);

  return (
    <>
      <div className="rp-page-head">
        <Link to="/corpus" style={{ color: 'var(--accent-l)', fontSize: 13, marginBottom: 4, display: 'inline-block' }}>
          &larr; Back to corpus
        </Link>
        <h1>{doc.document_title}</h1>
        <p>{doc.issuing_body} · {doc.document_type || doc.doc_type} · {doc.document_version || '—'}</p>
      </div>

      <div className="rp-table-wrap">
        {/* Metadata panel */}
        <div className="rp-section">
          <h3>Metadata</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: '8px 16px', fontSize: 13 }}>
            <span style={{ color: 'var(--doc-text-2)' }}>Document ID</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{doc.document_id}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Issuing Body</span>
            <span>{doc.issuing_body}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Document Type</span>
            <span>{doc.document_type || doc.doc_type}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Version</span>
            <span>{doc.document_version || '—'}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Publication Date</span>
            <span>{formatDate(doc.publication_date)}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Status</span>
            <span>
              {doc.ingestion_status === 'indexed' || doc.ingestion_status === 'success' ? (
                <span className="status ok">Current</span>
              ) : doc.ingestion_status === 'superseded' ? (
                <span className="status warn">Superseded</span>
              ) : (
                <span className="status warn">{doc.ingestion_status}</span>
              )}
            </span>

            <span style={{ color: 'var(--doc-text-2)' }}>Chunk Count</span>
            <span>{doc.chunk_count}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Qdrant Points</span>
            <span>{doc.qdrant_point_count}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Last Indexed</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{doc.last_indexed_at}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Run ID</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
              {doc.run_id ? (
                <Link to={`/corpus/runs?run=${doc.run_id}`} style={{ color: 'var(--accent-l)' }}>
                  {doc.run_id.substring(0, 8)}...
                </Link>
              ) : '—'}
            </span>

            <span style={{ color: 'var(--doc-text-2)' }}>Source URL</span>
            <span>
              {doc.source_url ? (
                <a href={doc.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-l)', fontSize: 12 }}>
                  View source ↗
                </a>
              ) : '—'}
            </span>

            <span style={{ color: 'var(--doc-text-2)' }}>Feed Source</span>
            <span>{doc.feed_id || '—'}</span>

            <span style={{ color: 'var(--doc-text-2)' }}>Archive Path</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, wordBreak: 'break-all' }}>{doc.archive_path || '—'}</span>
          </div>

          {/* Hash comparison */}
          <div style={{ marginTop: 20, padding: 16, background: 'var(--doc-bg)', borderRadius: 6, border: '1px solid var(--doc-border)' }}>
            <h3 style={{ marginTop: 0 }}>Hash Comparison</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 48px 1fr', alignItems: 'center', gap: 12 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 4 }}>PostgreSQL</div>
                <Tooltip tip={doc.pg_source_hash || ''}>
                  <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{hashAbbr(doc.pg_source_hash)}</code>
                </Tooltip>
              </div>
              <div style={{ textAlign: 'center' }}>
                {doc.hash_match ? (
                  <span style={{ color: '#22c55e', fontSize: 24 }}>✓</span>
                ) : (
                  <span style={{ color: '#ef4444', fontSize: 24 }}>✗</span>
                )}
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--doc-text-2)', marginBottom: 4 }}>Qdrant</div>
                <Tooltip tip={doc.qdrant_source_hash || ''}>
                  <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{hashAbbr(doc.qdrant_source_hash)}</code>
                </Tooltip>
              </div>
            </div>
            <div style={{ marginTop: 8, fontSize: 12 }}>
              {doc.hash_match ? (
                <span style={{ color: '#22c55e' }}>Hashes match</span>
              ) : (
                <span style={{ color: '#ef4444' }}>Hash mismatch — investigate</span>
              )}
            </div>
          </div>

          {/* Supersede chain */}
          {chain && chain.chain && chain.chain.length > 1 && (
            <div style={{ marginTop: 20, padding: 16, background: 'var(--doc-bg)', borderRadius: 6, border: '1px solid var(--doc-border)' }}>
              <h3 style={{ marginTop: 0 }}>Version Chain</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {chain.chain.map((v, i) => (
                  <span key={v.document_id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Link
                      to={`/corpus/${v.document_id}`}
                      style={{
                        padding: '6px 12px',
                        borderRadius: 6,
                        fontSize: 12,
                        fontFamily: 'var(--mono)',
                        textDecoration: 'none',
                        background: v.document_id === docId ? 'var(--accent-l)' : 'transparent',
                        color: v.document_id === docId ? '#fff' : 'var(--doc-text)',
                        border: v.document_id === docId ? '1px solid var(--accent-l)' : '1px solid var(--doc-border)',
                        opacity: v.is_superseded ? 0.6 : 1,
                      }}
                      title={`${v.document_version} · ${formatDate(v.publication_date)}`}
                    >
                      {v.document_version || v.document_id.substring(0, 12)}
                    </Link>
                    {i < chain.chain.length - 1 && <span style={{ color: 'var(--doc-text-3)' }}>→</span>}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Chunk list */}
        <div className="rp-section" style={{ marginTop: 24 }}>
          <h3>Chunks ({chunks.total})</h3>
          <div className="rp-table-wrap" style={{ maxHeight: 500, overflowY: 'auto' }}>
            <table className="rp-table">
              <thead>
                <tr>
                  <th style={{ width: 60 }}>Index</th>
                  <th style={{ width: 200 }}>Clause ID</th>
                  <th style={{ width: 80 }}>Status</th>
                  <th style={{ width: 80 }}>Char Start</th>
                  <th style={{ width: 80 }}>Char End</th>
                  <th style={{ width: 80 }}>Cross-refs</th>
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
                      <td className="mono">{ch.clause_id || '—'}</td>
                      <td>
                        <span className={`status ${ch.chunk_status === 'active' ? 'ok' : 'warn'}`}>
                          {ch.chunk_status}
                        </span>
                      </td>
                      <td className="mono">{ch.char_offset_start}</td>
                      <td className="mono">{ch.char_offset_end}</td>
                      <td className="mono">{ch.cross_refs?.length || 0}</td>
                    </tr>
                    {expandedChunk === ch.chunk_id && (
                      <tr key={`${ch.chunk_id}-exp`}>
                        <td colSpan={6} style={{ padding: '12px 16px', background: 'var(--doc-bg)' }}>
                          <pre style={{
                            fontFamily: 'var(--mono)',
                            fontSize: 12,
                            lineHeight: 1.6,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            maxHeight: 300,
                            overflowY: 'auto',
                            margin: 0,
                            padding: 12,
                            background: 'var(--doc-surface)',
                            border: '1px solid var(--doc-border)',
                            borderRadius: 4,
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
                <button onClick={() => setChunkPage(Math.max(1, chunkPage - 1))} disabled={chunkPage <= 1}>
                  &larr;
                </button>
                <button onClick={() => setChunkPage(chunkPage + 1)} disabled={chunkPage >= totalChunkPages}>
                  &rarr;
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
