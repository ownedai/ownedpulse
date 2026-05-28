import { useState, useEffect } from 'react';
import { getPdfPage, getPdfInfo } from '../../api/client';

export default function DocumentViewer({ document, onClose }) {
  const [pageNo, setPageNo] = useState(0);
  const [totalPages, setTotalPages] = useState(null);
  const [error, setError] = useState(false);
  const [gotoInput, setGotoInput] = useState('');

  const filePath = document?.source_local_path || '';

  // Fetch total page count on mount
  useEffect(() => {
    if (!filePath) return;
    setPageNo(0);
    setError(false);
    setTotalPages(null);
    setGotoInput('');
    getPdfInfo(filePath)
      .then((info) => setTotalPages(info.page_count))
      .catch(() => setTotalPages(null));
  }, [filePath]);

  if (!document) return null;

  const pdfUrl = filePath ? getPdfPage(filePath, pageNo) : null;

  function handlePrevPage() {
    setPageNo((p) => Math.max(0, p - 1));
    setError(false);
    setGotoInput('');
  }

  function handleNextPage() {
    if (totalPages !== null && pageNo + 1 >= totalPages) return;
    setPageNo((p) => p + 1);
    setError(false);
    setGotoInput('');
  }

  function handleGoto(e) {
    e.preventDefault();
    const n = parseInt(gotoInput, 10);
    if (!isNaN(n) && n >= 1 && totalPages !== null && n <= totalPages) {
      setPageNo(n - 1);
      setError(false);
      setGotoInput('');
    }
  }

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'var(--doc-bg)',
      zIndex: 100,
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid var(--doc-border)',
        background: 'var(--doc-surface)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 16,
      }}>
        <div>
          <div style={{
            fontFamily: 'var(--mono)',
            fontSize: 10.5,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--doc-text-2)',
            marginBottom: 6,
          }}>
            Document viewer
          </div>
          <h2 style={{
            fontSize: 17,
            fontWeight: 500,
            margin: '0 0 4px',
            color: 'var(--doc-text)',
            lineHeight: 1.3,
          }}>
            {document.document_title}
          </h2>
          <div style={{
            fontFamily: 'var(--mono)',
            fontSize: 11,
            color: 'var(--doc-text-2)',
          }}>
            {document.issuing_body} · v{document.document_version || '—'} · {document.superseded ? 'Superseded' : 'Current'}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'transparent',
            border: '1px solid var(--doc-border)',
            width: 28, height: 28,
            borderRadius: 3,
            cursor: 'pointer',
            color: 'var(--doc-text-2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M1 1l10 10M1 11L11 1" />
          </svg>
        </button>
      </div>

      {/* Page controls */}
      <div style={{
        padding: '10px 24px',
        borderBottom: '1px solid var(--doc-border)',
        background: 'var(--doc-bg)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        fontFamily: 'var(--mono)',
        fontSize: 12,
        color: 'var(--doc-text-2)',
      }}>
        <button
          onClick={handlePrevPage}
          disabled={pageNo <= 0}
          style={{
            background: 'var(--doc-surface)',
            border: '1px solid var(--doc-border)',
            width: 28, height: 28,
            borderRadius: 3,
            cursor: pageNo <= 0 ? 'not-allowed' : 'pointer',
            color: 'var(--doc-text-2)',
            fontSize: 12,
            opacity: pageNo <= 0 ? 0.4 : 1,
          }}
        >
          &larr;
        </button>
        <span>
          Page {pageNo + 1}{totalPages ? ` of ${totalPages}` : ''}
        </span>
        <button
          onClick={handleNextPage}
          disabled={totalPages !== null && pageNo + 1 >= totalPages}
          style={{
            background: 'var(--doc-surface)',
            border: '1px solid var(--doc-border)',
            width: 28, height: 28,
            borderRadius: 3,
            cursor: (totalPages !== null && pageNo + 1 >= totalPages) ? 'not-allowed' : 'pointer',
            color: 'var(--doc-text-2)',
            fontSize: 12,
            opacity: (totalPages !== null && pageNo + 1 >= totalPages) ? 0.4 : 1,
          }}
        >
          &rarr;
        </button>

        {/* Go to page */}
        <form onSubmit={handleGoto} style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 12 }}>
          <span style={{ fontSize: 11, color: 'var(--doc-text-3)' }}>Go to</span>
          <input
            type="text"
            value={gotoInput}
            onChange={(e) => setGotoInput(e.target.value)}
            placeholder="#"
            style={{
              width: 44,
              height: 26,
              textAlign: 'center',
              fontFamily: 'var(--mono)',
              fontSize: 12,
              border: '1px solid var(--doc-border)',
              borderRadius: 3,
              background: 'var(--doc-surface)',
              color: 'var(--doc-text)',
              outline: 'none',
            }}
          />
        </form>
      </div>

      {/* PDF content */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: 24,
        background: '#E2E8F0',
      }}>
        {!filePath && (
          <div style={{
            padding: 32,
            fontFamily: 'var(--mono)',
            fontSize: 12,
            color: 'var(--doc-text-2)',
            textAlign: 'center',
          }}>
            Document file path not available.
          </div>
        )}
        {filePath && pdfUrl && !error && (
          <img
            src={pdfUrl}
            alt={`Page ${pageNo + 1}`}
            style={{
              maxWidth: '100%',
              boxShadow: '0 4px 24px rgba(15, 23, 42, 0.1)',
              border: '1px solid var(--doc-border-strong)',
              background: '#fff',
            }}
            onError={() => setError(true)}
          />
        )}
        {(error || (filePath && !pdfUrl)) && (
          <div style={{
            padding: 32,
            fontFamily: 'var(--mono)',
            fontSize: 12,
            color: 'var(--doc-text-2)',
            textAlign: 'center',
          }}>
            PDF not available for this document.
          </div>
        )}
      </div>
    </div>
  );
}
