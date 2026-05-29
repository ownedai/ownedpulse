import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getAdminHealth, getAdminFeeds, toggleFeed, triggerPipelineRun, getAdminModels, updateActiveModel } from '../../api/client';

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
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(() => {
    setLoading(true);
    getAdminHealth()
      .then(setHealth)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

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
      </div>
    </div>
  );
}

function Toggle({ checked, onChange }) {
  return (
    <label style={{ position: 'relative', display: 'inline-block', width: 36, height: 20, cursor: 'pointer', flexShrink: 0 }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }}
      />
      <span style={{
        position: 'absolute', inset: 0, borderRadius: 20,
        background: checked ? 'var(--accent-l)' : 'var(--doc-border-strong)',
        transition: 'background 150ms ease',
      }} />
      <span style={{
        position: 'absolute',
        width: 14, height: 14,
        borderRadius: 7,
        background: '#fff',
        top: 3, left: checked ? 19 : 3,
        transition: 'left 150ms ease',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </label>
  );
}

function FeedsPanel() {
  const [feeds, setFeeds] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAdminFeeds()
      .then(setFeeds)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="rp-card">
      <SectionLabel>Feed Management</SectionLabel>
      {loading ? (
        <div style={{ color: 'var(--doc-text-2)', fontSize: 13 }}>Loading...</div>
      ) : (
        <table className="rp-table" style={{ margin: 0 }}>
          <thead>
            <tr>
              <th>Feed Name</th>
              <th>URL</th>
              <th style={{ width: 70 }}>Enabled</th>
            </tr>
          </thead>
          <tbody>
            {feeds.map((f) => (
              <tr key={f.feed_id}>
                <td>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{f.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--doc-text-3)' }}>
                    {f.feed_id} · {f.feed_type}
                  </div>
                </td>
                <td>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--doc-text-2)' }}>
                    {f.url ? (f.url.length > 45 ? f.url.substring(0, 45) + '…' : f.url) : '—'}
                  </span>
                </td>
                <td>
                  <Toggle
                    checked={f.enabled}
                    onChange={(e) => {
                      toggleFeed(f.feed_id, e.target.checked).then((updated) => {
                        setFeeds((prev) => prev.map((pf) => pf.feed_id === updated.feed_id ? updated : pf));
                      }).catch(() => {});
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TriggerPanel() {
  const [triggering, setTriggering] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const trigger = () => {
    setTriggering(true);
    setResult(null);
    setError(null);
    triggerPipelineRun()
      .then((data) => { setResult(data); })
      .catch((err) => setError(err.message))
      .finally(() => setTriggering(false));
  };

  const webhookError = error === 'Webhook URL not configured';

  return (
    <div className="rp-card">
      <SectionLabel>Pipeline Trigger</SectionLabel>
      {webhookError ? (
        <div style={{ padding: 12, background: 'var(--warn-tint)', borderRadius: 6, color: 'var(--warn-text)', fontSize: 13, border: '1px solid var(--warn-tint-border)' }}>
          Webhook not configured. Set <code style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>n8n_trigger_webhook</code> in system_config.
        </div>
      ) : (
        <>
          <button
            onClick={trigger}
            disabled={triggering || !!result}
            style={{
              display: 'block', width: '100%',
              padding: '10px 20px',
              background: result ? 'var(--ok)' : triggering ? '#94a3b8' : 'var(--accent-l)',
              color: '#fff', border: 'none', borderRadius: 6,
              cursor: triggering || result ? 'default' : 'pointer',
              fontSize: 14, fontWeight: 500,
              transition: 'background 200ms ease',
            }}
          >
            {result ? '✓ Run started' : triggering ? 'Triggering…' : 'Run Pipeline Now'}
          </button>
          {result && (
            <div style={{ marginTop: 10, fontSize: 13, color: 'var(--doc-text-2)' }}>
              <Link to={`/corpus/runs?run=${result.run_id}`} style={{ color: 'var(--accent-l)' }}>
                ● View in Run Log →
              </Link>
            </div>
          )}
        </>
      )}
      {error && !webhookError && (
        <div style={{ marginTop: 10, padding: 10, background: 'var(--err-tint)', borderRadius: 4, color: 'var(--err-text)', fontSize: 12, border: '1px solid var(--err-tint-border)' }}>
          {error}
        </div>
      )}
    </div>
  );
}

function ModelPanel() {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState('');
  const [updating, setUpdating] = useState(false);
  const [message, setMessage] = useState(null);

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
        <FeedsPanel />
        <TriggerPanel />
        <ModelPanel />
      </div>
    </>
  );
}
