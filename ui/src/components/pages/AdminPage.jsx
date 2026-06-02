import { useState, useEffect, useCallback } from 'react';
import { getAdminHealth, getAdminModels, updateActiveModel, getSchedulerStatus, triggerSchedulerNow, pauseScheduler, resumeScheduler } from '../../api/client';
import { useModelStatusContext } from '../../context/ModelStatusContext';

function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em',
      textTransform: 'uppercase', color: 'var(--accent-l)', fontWeight: 600,
      marginBottom: 14,
    }}>
      {children}
    </div>
  );
}

function HealthPanel() {
  const [health, setHealth] = useState(null);
  const [sched, setSched] = useState(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);

  const fetch = useCallback(() => {
    setLoading(true);
    Promise.all([
      getAdminHealth().catch(() => null),
      getSchedulerStatus().catch(() => null),
    ]).then(([h, s]) => {
      setHealth(h);
      setSched(s);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  async function handleTrigger() {
    setTriggering(true);
    try { await triggerSchedulerNow(); } catch (_) {}
    setTriggering(false);
  }

  async function handlePauseResume() {
    try {
      if (sched?.scheduler_running) await pauseScheduler();
      else await resumeScheduler();
      const updated = await getSchedulerStatus();
      setSched(updated);
    } catch (_) {}
  }

  const services = [
    {
      key: 'qdrant',
      label: 'Qdrant',
      meta: (s) => s?.points_count != null ? `${s.points_count.toLocaleString()} points` : null,
    },
    {
      key: 'postgres',
      label: 'PostgreSQL',
      meta: (s) => s?.document_count != null ? `${s.document_count.toLocaleString()} documents` : null,
    },
    {
      key: 'ollama',
      label: 'Ollama',
      meta: (s) => s?.active_model ? s.active_model : null,
      warn: (s) => s?.response_ms > 2000,
    },
  ];

  const nextRun = sched?.next_run_time
    ? new Date(sched.next_run_time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className="rp-card">
      <div className="rp-card-head" style={{ marginBottom: 16 }}>
        <SectionLabel>System Health</SectionLabel>
        <button onClick={fetch} className="action" style={{ fontSize: 12, marginTop: -8 }}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {services.map(({ key, label, meta, warn }) => {
          const s = health?.[key];
          const ok = s?.status === 'ok';
          const isWarn = warn?.(s);
          const dotColor = !ok ? 'var(--err)' : isWarn ? 'var(--warn)' : 'var(--ok)';
          const metaText = meta?.(s);
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: dotColor, flexShrink: 0 }} />
              <span style={{ fontWeight: 500, minWidth: 80 }}>{label}</span>
              {metaText && (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)' }}>{metaText}</span>
              )}
              {!ok && s?.message && (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: isWarn ? 'var(--warn-text)' : 'var(--err-text)' }}>
                  {s.message}
                </span>
              )}
            </div>
          );
        })}

        {/* Scheduler row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, marginTop: 4, paddingTop: 10, borderTop: '1px solid var(--doc-border)' }}>
          <span style={{ width: 8, height: 8, borderRadius: 4, background: sched?.scheduler_running ? 'var(--ok)' : 'var(--warn)', flexShrink: 0 }} />
          <span style={{ fontWeight: 500, minWidth: 80 }}>Scheduler</span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--doc-text-2)', flex: 1 }}>
            {sched?.scheduler_running ? `Next run: ${nextRun || sched.schedule}` : 'Not running'}
          </span>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            style={{ padding: '2px 8px', fontSize: 11, fontFamily: 'var(--mono)', borderRadius: 3, border: '1px solid var(--accent-l)', color: 'var(--accent-l)', background: 'transparent', cursor: 'pointer' }}
          >
            {triggering ? 'Triggering…' : 'Run now'}
          </button>
          <button
            onClick={handlePauseResume}
            style={{ padding: '2px 8px', fontSize: 11, fontFamily: 'var(--mono)', borderRadius: 3, border: '1px solid var(--doc-border)', color: 'var(--doc-text-2)', background: 'transparent', cursor: 'pointer' }}
          >
            {sched?.scheduler_running ? 'Pause' : 'Resume'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ModelPanel() {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState('');
  const [updating, setUpdating] = useState(false);
  const [message, setMessage] = useState(null);
  const { recheck } = useModelStatusContext();

  useEffect(() => {
    getAdminModels()
      .then((d) => { setData(d); setSelected(d.active_model || ''); })
      .catch(() => {});
  }, []);

  const handleChange = (model) => {
    setUpdating(true);
    setMessage(null);
    updateActiveModel(model)
      .then(() => {
        setSelected(model);
        setMessage({ type: 'ok', text: `Active model changed to ${model}.` });
        recheck();
      })
      .catch((err) => {
        setMessage({ type: 'err', text: err.message });
      })
      .finally(() => setUpdating(false));
  };

  return (
    <div className="rp-card">
      <SectionLabel>Model Selection</SectionLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ fontSize: 12, color: 'var(--doc-text-2)', marginBottom: 2 }}>Active LLM Model</div>
        {data ? (
          <>
            <select
              value={selected}
              onChange={(e) => handleChange(e.target.value)}
              disabled={updating}
              style={{
                padding: '8px 12px', fontSize: 13.5, borderRadius: 5,
                border: '1px solid var(--doc-border)',
                background: 'var(--doc-surface)', color: 'var(--doc-text)',
                fontFamily: 'var(--mono)', cursor: 'pointer',
              }}
            >
              {data.available_models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            {updating && <div style={{ fontSize: 12, color: 'var(--doc-text-2)' }}>Updating…</div>}
            {message && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {message.type === 'ok' && (
                  <span style={{ fontSize: 28, color: 'var(--ok)' }}>✓</span>
                )}
                <div style={{
                  padding: '6px 10px', borderRadius: 4, fontSize: 12,
                  background: message.type === 'ok' ? 'var(--ok-tint)' : 'var(--err-tint)',
                  color: message.type === 'ok' ? 'var(--ok-text)' : 'var(--err-text)',
                  border: `1px solid ${message.type === 'ok' ? 'var(--ok-tint-border)' : 'var(--err-tint-border)'}`,
                }}>
                  {message.text}
                </div>
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--doc-text-3)' }}>
              Changing model affects all subsequent queries.
            </div>
          </>
        ) : (
          <div style={{ color: 'var(--doc-text-2)', fontSize: 13 }}>Loading models...</div>
        )}
      </div>
    </div>
  );
}

export default function AdminPage() {
  return (
    <>
      <div className="rp-page-head">
        <div>
          <h1>Admin</h1>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 20 }}>
        <HealthPanel />
        <ModelPanel />
      </div>
    </>
  );
}
