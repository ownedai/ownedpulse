import Tooltip, { InfoIcon } from '../common/Tooltip';

const DEPTHS = [
  { label: 'Low', value: 'low', hint: 'N=2' },
  { label: 'Standard', value: 'standard', hint: 'N=3' },
  { label: 'Deep', value: 'deep', hint: 'N=5' },
];

export default function RetrievalSettings({
  depth = 'standard',
  topK = 10,
  scoreThreshold = 0.60,
  onChange,
}) {
  const scorePct = ((scoreThreshold - 0.40) / (0.90 - 0.40)) * 100;

  function setDepth(v) {
    onChange?.({ depth: v, topK, scoreThreshold });
  }

  function setTopK(v) {
    const val = Math.min(20, Math.max(5, v));
    onChange?.({ depth, topK: val, scoreThreshold });
  }

  function setThreshold(v) {
    onChange?.({ depth, topK, scoreThreshold: v });
  }

  return (
    <div className="rp-retrieval">
      {/* Query depth */}
      <div className="field">
        <span className="field-label">
          Query depth
          <InfoIcon tip="Controls how many search variations are generated. Deep = more thorough but slower. Standard recommended for most queries." />
        </span>
        <div className="seg">
          {DEPTHS.map((d) => (
            <button
              key={d.value}
              className={depth === d.value ? 'on' : ''}
              onClick={() => setDepth(d.value)}
            >
              {d.label} <span style={{ opacity: 0.6 }}>({d.hint})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Top-K */}
      <div className="field">
        <span className="field-label">
          Sources per variation
          <InfoIcon tip="Number of source chunks retrieved per search variation before relevance filtering. Higher values improve recall, increase latency. Range 5–20." />
        </span>
        <div className="num">
          <button onClick={() => setTopK(topK - 1)}>&minus;</button>
          <input
            type="text"
            value={topK}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              if (!isNaN(v)) setTopK(v);
            }}
          />
          <button onClick={() => setTopK(topK + 1)}>+</button>
        </div>
      </div>

      {/* Score threshold */}
      <div className="field" style={{ flex: 1, maxWidth: 320 }}>
        <span className="field-label">
          Min. relevance
          <InfoIcon tip="Chunks scoring below this threshold are excluded from results entirely. Default: 0.60." />
        </span>
        <div className="slider-wrap">
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--shell-dim)' }}>0.40</span>
          <div className="slider">
            <div className="fill" style={{ width: scorePct + '%' }} />
            <div className="thumb" style={{ left: scorePct + '%' }} />
          </div>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--shell-dim)' }}>0.90</span>
          <span className="slider-val">{scoreThreshold.toFixed(2)}</span>
        </div>
      </div>

      <button
        className="reset"
        onClick={() => onChange?.({ depth: 'standard', topK: 10, scoreThreshold: 0.60 })}
      >
        Reset
      </button>
    </div>
  );
}
