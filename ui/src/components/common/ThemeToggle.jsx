import { useState, useEffect } from 'react';
import Tooltip from './Tooltip';

const STORAGE_KEY = 'regpulse-theme';

function getInitialTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') return stored;
  } catch {}
  return 'dark';
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {}
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const isDark = theme === 'dark';
  const label = isDark ? 'Switch content panel to light mode' : 'Switch content panel to dark mode';

  return (
    <Tooltip tip={label} placement="below">
      <button
        className="theme-toggle"
        onClick={() => setTheme(isDark ? 'light' : 'dark')}
        aria-label={label}
        data-testid="theme-toggle"
      >
        {isDark ? (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="3" />
            <path d="M8 1.5v1.6M8 12.9v1.6M14.5 8h-1.6M3.1 8H1.5M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1M12.6 12.6l-1.1-1.1M4.5 4.5L3.4 3.4" />
          </svg>
        ) : (
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M13.5 9.7A5.5 5.5 0 0 1 6.3 2.5a.4.4 0 0 0-.5-.5 6 6 0 1 0 7.7 7.7.4.4 0 0 0-.5-.5z" fill="currentColor" stroke="none" opacity="0.85" />
          </svg>
        )}
      </button>
    </Tooltip>
  );
}
