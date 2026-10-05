import { useState, useCallback } from 'react';
import { submitQuery, getQuery } from '../api/client';

// Generation on a shared or memory-constrained GPU can take minutes when the
// model has to be reloaded, so this sits above the API's own OLLAMA_TIMEOUT
// (180s default) — the API's 504 is the better message when it wins the race.
const QUERY_TIMEOUT_MS = 210000;

export default function useQuery() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [queryText, setQueryText] = useState('');

  const execute = useCallback(async (query, filters = {}, retrievalParams = {}) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setQueryText(query);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), QUERY_TIMEOUT_MS);
    try {
      const data = await submitQuery(
        {
          query,
          filters: Object.keys(filters).length ? filters : {},
          retrieval_params: Object.keys(retrievalParams).length
            ? retrievalParams
            : { query_depth: 'standard', top_k: 10, score_threshold: 0.60 },
        },
        controller.signal
      );
      setResult(data);
    } catch (err) {
      if (err.name === 'AbortError') {
        setError('The query timed out. The model may still be loading or the GPU is busy — try again.');
      } else {
        setError(err.message);
      }
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  }, []);

  const loadCached = useCallback(async (queryId) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await getQuery(queryId);
      setResult(data);
      setQueryText(data.query_text || '');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
    setQueryText('');
  }, []);

  return { result, loading, error, queryText, execute, loadCached, clear };
}
