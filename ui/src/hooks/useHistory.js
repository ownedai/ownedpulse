import { useState, useEffect, useCallback } from 'react';
import { fetchHistory } from '../api/client';

export function useHistory() {
  const [history, setHistory] = useState([]);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchHistory();
      setHistory(data);
    } catch {
      // silent fail
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { history, refresh };
}
