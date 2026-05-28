import { useState } from 'react';

export default function QueryInput({ value, onChange, onSubmit, disabled }) {
  const [local, setLocal] = useState(value || '');

  function handleChange(e) {
    setLocal(e.target.value);
    onChange?.(e.target.value);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !disabled && local.trim()) {
      onSubmit?.(local.trim());
    }
  }

  function handleSubmit() {
    if (!disabled && local.trim()) {
      onSubmit?.(local.trim());
    }
  }

  return (
    <div className="rp-landing">
      <div className="query-row">
        <div className="query-input">
          <input
            type="text"
            placeholder="Ask a regulatory question…"
            value={local}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            disabled={disabled}
          />
        </div>
        <button
          className="query-submit"
          onClick={handleSubmit}
          disabled={disabled || !local.trim()}
        >
          Submit
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 8h10M9 4l4 4-4 4" />
          </svg>
        </button>
      </div>
    </div>
  );
}
