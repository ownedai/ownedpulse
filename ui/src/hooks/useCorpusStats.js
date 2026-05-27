import { useState, useEffect } from 'react';
import { fetchCorpusStats } from '../api/client';

export function useCorpusStats() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetchCorpusStats()
      .then(setStats)
      .catch(() => {});
  }, []);

  return { stats };
}
