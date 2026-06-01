import { useState, useEffect, useRef } from 'react';

const POLL_INTERVAL = 4000;

export default function useModelStatus() {
  const [status, setStatus] = useState({
    loaded: false, model: null, checked: false,
    embed_loaded: false, embed_model: null,
  });
  const timerRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    // Trigger warmup immediately on mount
    fetch('/api/admin/warmup', { method: 'POST' }).catch(() => {});

    const check = async () => {
      try {
        const res = await fetch('/api/admin/model-status');
        if (!mountedRef.current) return;
        if (res.ok) {
          const data = await res.json();
          setStatus({
            loaded: !!data.loaded, model: data.model, checked: true,
            embed_loaded: !!data.embed_loaded, embed_model: data.embed_model || 'mxbai-embed-large',
          });
          if (!data.loaded || !data.embed_loaded) {
            timerRef.current = setTimeout(check, POLL_INTERVAL);
          }
        }
      } catch {
        if (mountedRef.current) {
          timerRef.current = setTimeout(check, POLL_INTERVAL);
        }
      }
    };

    check();

    return () => {
      mountedRef.current = false;
      clearTimeout(timerRef.current);
    };
  }, []);

  // Re-check after a model change (called from AdminPage)
  const recheck = () => {
    clearTimeout(timerRef.current);
    setStatus(s => ({ ...s, loaded: false, embed_loaded: false }));
    fetch('/api/admin/warmup', { method: 'POST' }).catch(() => {});
    const poll = async () => {
      try {
        const res = await fetch('/api/admin/model-status');
        if (!mountedRef.current) return;
        if (res.ok) {
          const data = await res.json();
          setStatus({
            loaded: !!data.loaded, model: data.model, checked: true,
            embed_loaded: !!data.embed_loaded, embed_model: data.embed_model || 'mxbai-embed-large',
          });
          if (!data.loaded || !data.embed_loaded) timerRef.current = setTimeout(poll, POLL_INTERVAL);
        }
      } catch {
        if (mountedRef.current) timerRef.current = setTimeout(poll, POLL_INTERVAL);
      }
    };
    setTimeout(poll, 1500);
  };

  return { ...status, recheck };
}
