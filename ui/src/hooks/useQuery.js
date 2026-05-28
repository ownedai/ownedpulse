import { useState, useCallback } from 'react';
import { submitQuery } from '../api/client';

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
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
    setQueryText('');
  }, []);

  return { result, loading, error, queryText, execute, clear };
}
