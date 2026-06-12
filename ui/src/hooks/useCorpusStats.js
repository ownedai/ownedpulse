import { useState, useEffect, useCallback } from 'react';
import { getCorpusStats } from '../api/client';

export default function useCorpusStats() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  const fetch = useCallback(() => {
    let cancelled = false;
    getCorpusStats()
      .then(data => { if (!cancelled) setStats(data); })
      .catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const cleanup = fetch();
    // Refresh when bootstrap completes
    const onComplete = () => { fetch(); };
    window.addEventListener('regpulse:bootstrap-complete', onComplete);
    return () => {
      cleanup();
      window.removeEventListener('regpulse:bootstrap-complete', onComplete);
    };
  }, [fetch]);

  return { stats, error };
}
