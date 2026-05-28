export function Mark({ size = 'sz-24', onLight = false }) {
  return (
    <span className={`rp-mark ${size} ${onLight ? 'on-light' : ''}`}>
      <span className="sq" />
      <span className="ci" />
    </span>
  );
}

export function Wordmark({ onLight = false }) {
  return (
    <span className={`rp-wm ${onLight ? 'on-light' : ''}`}>
      owned<em>ai</em>
    </span>
  );
}

export default function Logo({ onLight = false, showWordmark = true }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <Mark size="sz-24" onLight={onLight} />
      {showWordmark && <Wordmark onLight={onLight} />}
    </span>
  );
}
