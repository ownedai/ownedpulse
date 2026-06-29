import { useState, useEffect, useCallback, useRef } from 'react';
import { getCorpusStats } from '../api/client';

export default function useCorpusStats() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

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
    window.addEventListener('ownedpulse:bootstrap-complete', onComplete);

    return () => {
      cleanup();
      window.removeEventListener('ownedpulse:bootstrap-complete', onComplete);
    };
  }, [fetch]);

  // Poll during active ingestion, refresh when it completes
  useEffect(() => {
    if (stats?.ingestion_active) {
      intervalRef.current = setInterval(fetch, 5000);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
        fetch(); // final refresh to pick up new counts
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [stats?.ingestion_active, fetch]);

  return { stats, error };
}
