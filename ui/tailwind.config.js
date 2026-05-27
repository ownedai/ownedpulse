/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        shell: {
          bg: '#0F172A',
          surface: '#1E293B',
          border: '#334155',
          muted: '#94A3B8',
        },
        accent: {
          dark: '#60A5FA',
          light: '#2563EB',
          hover: '#1D4ED8',
          bg: '#DBEAFE',
        },
        panel: {
          bg: '#F8FAFC',
          surface: '#FFFFFF',
        },
        primary: '#0F172A',
        secondary: '#64748B',
        success: '#10B981',
        warning: '#F59E0B',
        error: '#EF4444',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
