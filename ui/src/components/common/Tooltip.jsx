export default function Tooltip({ tip, children, placement = 'above' }) {
  return (
    <span className={`rp-tip placement-${placement === 'below' ? 'below' : 'above'}`}>
      {children}
      <span className="tip-body">{tip}</span>
    </span>
  );
}

export function InfoIcon({ tip, placement = 'above' }) {
  return (
    <Tooltip tip={tip} placement={placement}>
      <span className="rp-i">i</span>
    </Tooltip>
  );
}
