import { useState, useEffect, useCallback } from 'react';
import { getAdminHealth, getAdminFeeds, toggleFeed, triggerPipelineRun, getAdminModels, updateActiveModel } from '../../api/client';
import { formatDateTime } from '../../dateFormat';

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

  return (
    <div className="rp-card">
      <div className="rp-card-head">
        <h3>System Health</h3>
        <button onClick={fetch} className="action" style={{ fontSize: 12 }}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {['qdrant', 'postgres', 'ollama'].map((svc) => {
          const s = health?.[svc];
          const ok = s?.status === 'ok';
          return (
            <div key={svc} style={{
              padding: 12,
              background: 'var(--doc-bg)',
              borderRadius: 6,
              border: '1px solid var(--doc-border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <div>
                <div style={{ fontWeight: 500, fontSize: 14, textTransform: 'capitalize' }}>{svc}</div>
                <div style={{ fontSize: 11, color: 'var(--doc-text-3)', fontFamily: 'var(--mono)', marginTop: 2 }}>
                  {svc === 'qdrant' && `Points: ${s?.points_count?.toLocaleString() || '—'}`}
                  {svc === 'postgres' && `Docs: ${s?.document_count?.toLocaleString() || '—'}`}
                  {svc === 'ollama' && `Model: ${s?.active_model || '—'}`}
                </div>
              </div>
              <span style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: ok ? '#22c55e' : '#ef4444',
              }}>
                <span style={{ width: 8, height: 8, borderRadius: 4, background: ok ? '#22c55e' : '#ef4444' }} />
                {ok ? 'Online' : s?.message || 'Error'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
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
      <div className="rp-card-head">
        <h3>Feed Management</h3>
      </div>
      {loading ? (
        <div style={{ color: 'var(--doc-text-2)', fontSize: 13 }}>Loading...</div>
      ) : (
        <table className="rp-table" style={{ margin: 0 }}>
          <thead>
            <tr>
              <th>Feed</th>
              <th style={{ width: 60 }}>Enabled</th>
            </tr>
          </thead>
          <tbody>
            {feeds.map((f) => (
              <tr key={f.feed_id}>
                <td>
                  <div style={{ fontSize: 13 }}>{f.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--doc-text-3)' }}>
                    {f.feed_id} · {f.feed_type}
                  </div>
                </td>
                <td>
                  <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={f.enabled}
                      onChange={(e) => {
                        toggleFeed(f.feed_id, e.target.checked).then((updated) => {
                          setFeeds((prev) => prev.map((pf) => pf.feed_id === updated.feed_id ? updated : pf));
                        }).catch(() => {});
                      }}
                      style={{ accentColor: 'var(--accent-l)', width: 18, height: 18, cursor: 'pointer' }}
                    />
                  </label>
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
      .then((data) => {
        setResult(data);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setTriggering(false));
  };

  const webhookError = error === 'Webhook URL not configured';

  return (
    <div className="rp-card">
      <div className="rp-card-head">
        <h3>Manual Trigger</h3>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {webhookError ? (
          <div style={{
            padding: 12,
            background: '#fef3c7',
            borderRadius: 6,
            color: '#92400e',
            fontSize: 13,
            border: '1px solid #fcd34d',
          }}>
            Webhook not configured. Set n8n_trigger_webhook in system_config.
          </div>
        ) : (
          <button
            onClick={trigger}
            disabled={triggering}
            style={{
              padding: '10px 20px',
              background: triggering ? '#94a3b8' : 'var(--accent-l)',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: triggering ? 'not-allowed' : 'pointer',
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {triggering ? 'Triggering...' : 'Run Pipeline Now'}
          </button>
        )}
        {result && (
          <div style={{
            padding: 12,
            background: '#dcfce7',
            borderRadius: 6,
            color: '#166534',
            fontSize: 12,
            border: '1px solid #bbf7d0',
          }}>
            <div>Pipeline triggered</div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, marginTop: 4 }}>
              Run ID: {result.run_id}
            </div>
            <a href={`/corpus/runs?run=${result.run_id}`} style={{ color: 'var(--accent-l)', fontSize: 12, marginTop: 4, display: 'inline-block' }}>
              View in Run Log &rarr;
            </a>
          </div>
        )}
        {error && !webhookError && (
          <div style={{
            padding: 12,
            background: '#fef2f2',
            borderRadius: 6,
            color: '#991b1b',
            fontSize: 12,
            border: '1px solid #fecaca',
          }}>
            {error}
          </div>
        )}
      </div>
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
      .then((d) => {
        setData(d);
        setSelected(d.active_model || '');
      })
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
      <div className="rp-card-head">
        <h3>Model Selection</h3>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {data ? (
          <>
            <select
              value={selected}
              onChange={(e) => handleChange(e.target.value)}
              disabled={updating}
              style={{
                padding: '8px 12px',
                fontSize: 14,
                borderRadius: 6,
                border: '1px solid var(--doc-border)',
                background: 'var(--doc-surface)',
                color: 'var(--doc-text)',
                fontFamily: 'var(--mono)',
                cursor: 'pointer',
              }}
            >
              {data.available_models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            {updating && <div style={{ fontSize: 12, color: 'var(--doc-text-2)' }}>Updating...</div>}
            {message && (
              <div style={{
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                background: message.type === 'ok' ? '#dcfce7' : '#fef2f2',
                color: message.type === 'ok' ? '#166534' : '#991b1b',
              }}>
                {message.text}
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--doc-text-3)', marginTop: 8 }}>
              Changing model affects all subsequent queries. Change is logged in query_history.
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
          <p>System management and configuration.</p>
        </div>
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
        gap: 20,
      }}>
        <HealthPanel />
        <FeedsPanel />
        <TriggerPanel />
        <ModelPanel />
      </div>
    </>
  );
}
