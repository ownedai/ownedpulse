import { useState, useCallback } from 'react';
import { submitQuery as apiSubmitQuery } from '../api/client';

export function useQuery() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const submitQuery = useCallback(async (queryText, filters) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await apiSubmitQuery(queryText, filters);
      setResult(data);
    } catch (e) {
      setError(e.message || 'An error occurred while querying.');
    } finally {
      setLoading(false);
    }
  }, []);

  const clearResult = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return { result, loading, error, submitQuery, clearResult };
}
