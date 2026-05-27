import { useState, useEffect } from 'react';
import ProvMetadata from '../common/ProvMetadata';
import { fetchPdfPage } from '../../api/client';

export default function SourcePanel({ citation, onClose }) {
  const [currentChunkIdx, setCurrentChunkIdx] = useState(0);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [pdfError, setPdfError] = useState(null);

  useEffect(() => {
    setCurrentChunkIdx(0);
  }, [citation?.chunk_id]);

  useEffect(() => {
    if (citation?.local_file_path) {
      setPdfError(null);
      fetchPdfPage(citation.local_file_path, citation.page_number || 0)
        .then((blob) => setPdfUrl(URL.createObjectURL(blob)))
        .catch(() => setPdfError('PDF page could not be loaded'));
    } else {
      setPdfUrl(null);
      setPdfError('PDF not available');
    }

    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    };
  }, [citation?.chunk_id, citation?.local_file_path, citation?.page_number]);

  return (
    <aside className="w-[40%] min-w-[400px] bg-white border-l border-slate-200 overflow-y-auto flex flex-col">
      <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-3.5 flex items-center justify-between z-10">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-800 truncate">{citation.title}</h3>
          <p className="text-xs text-secondary mt-0.5">{citation.agency}</p>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 p-1 rounded hover:bg-slate-100 transition-colors"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M4.5 4.5L13.5 13.5M13.5 4.5L4.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="flex-1 px-5 py-4 space-y-5">
        <div>
          <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
            Retrieved Chunk
          </h4>
          <div className="bg-[#F1F5F9] rounded-lg p-4 font-mono text-xs leading-relaxed text-slate-700 max-h-64 overflow-y-auto">
            {citation.chunk_text}
          </div>
        </div>

        <ProvMetadata citation={citation} />

        {citation.local_file_path && (
          <div>
            <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
              PDF Page
            </h4>
            {pdfError ? (
              <div className="text-xs text-slate-400 bg-slate-50 rounded-lg p-4 text-center">
                {pdfError}
              </div>
            ) : pdfUrl ? (
              <img src={pdfUrl} alt="PDF page" className="w-full rounded-lg border border-slate-200" />
            ) : (
              <div className="text-xs text-slate-400 bg-slate-50 rounded-lg p-4 text-center">
                Loading...
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
