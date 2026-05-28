import { useState, useEffect } from 'react';
import { getQueryHistory } from '../api/client';

export default function useHistory(limit = 10) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  function refresh() {
    setLoading(true);
    getQueryHistory(limit, 0)
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, [limit]);

  return { items, loading, refresh };
}
