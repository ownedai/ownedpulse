import { useState, useEffect } from 'react';
import { getTrace } from '../../api/client';

function Step({ number, name, latency, open: defaultOpen, children }) {
  const [open, setOpen] = useState(defaultOpen !== false);

  return (
    <div className={`step${open ? ' open' : ' collapsed'}`}>
      <div className="step-head" onClick={() => setOpen((v) => !v)}>
        <span className="name">
          <span className="ord">{number}</span>
          {name}
        </span>
        <span className="latency">
          {latency}
          <svg className="chev" width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M3 4.5l3 3 3-3" />
          </svg>
        </span>
      </div>
      {open && <div className="step-body">{children}</div>}
    </div>
  );
}

function Row({ label, value, accent }) {
  return (
    <div className="row">
      <span className="k">{label}</span>
      <span className={`v${accent ? ' accent' : ''}`}>{value}</span>
    </div>
  );
}

export default function LangfuseDrawer({ traceId, onClose }) {
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!traceId) return;
    setLoading(true);
    setError(null);
    getTrace(traceId)
      .then(setTrace)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [traceId]);

  return (
    <div className="rp-drawer">
      <div className="head">
        <div>
          <div className="lbl">Langfuse trace</div>
          <h3>{traceId || '—'}</h3>
          {trace && (
            <div className="meta">
              total latency <span className="v">{trace.latency ? `${trace.latency.toFixed(0)} ms` : '—'}</span>
              {trace.observations && ` · ${trace.observations.length} steps`}
            </div>
          )}
          {loading && <div className="meta">Loading...</div>}
        </div>
        <button className="close" onClick={onClose} aria-label="Close trace">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M1 1l10 10M1 11L11 1" />
          </svg>
        </button>
      </div>
      <div className="scroll">
        {error && (
          <div className="note" style={{ color: 'var(--err-text)' }}>
            Failed to load trace: {error}
          </div>
        )}
        {loading && !error && (
          <div className="note">Fetching trace data...</div>
        )}
        {trace && trace.observations && trace.observations.length > 0 && (
          <>
            {trace.observations.map((obs, i) => (
              <Step
                key={i}
                number={i + 1}
                name={obs.name || obs.type || `Step ${i + 1}`}
                latency={obs.latency ? `${obs.latency.toFixed(0)} ms` : '—'}
                open={i < 2}
              >
                {obs.model && <Row label="model" value={obs.model} />}
                {obs.input && (
                  <Row label="input" value={typeof obs.input === 'string' ? obs.input.slice(0, 200) : JSON.stringify(obs.input).slice(0, 200)} />
                )}
                {obs.output && (
                  <Row label="output" value={typeof obs.output === 'string' ? obs.output.slice(0, 200) : JSON.stringify(obs.output).slice(0, 200)} />
                )}
                {obs.usage && (obs.usage.promptTokens || obs.usage.completionTokens) && (
                  <Row label="tokens" value={`${obs.usage.promptTokens || 0} prompt + ${obs.usage.completionTokens || 0} completion`} />
                )}
                {obs.metadata && (
                  <Row label="metadata" value={JSON.stringify(obs.metadata).slice(0, 300)} />
                )}
              </Step>
            ))}
          </>
        )}
        {trace && (!trace.observations || trace.observations.length === 0) && (
          <div className="note">No observation data available for this trace.</div>
        )}
        {!trace && !loading && !error && (
          <div className="note">Trace data not available.</div>
        )}
      </div>
    </div>
  );
}
