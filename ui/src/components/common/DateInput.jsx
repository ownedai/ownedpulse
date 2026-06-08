import { useState, useEffect } from 'react';

function isoToEu(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-');
  if (!y || !m || !d) return iso || '';
  return `${d}.${m}.${y}`;
}

function euToIso(eu) {
  const trimmed = String(eu || '').trim();
  if (!trimmed) return '';
  const match = trimmed.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!match) return '';
  return `${match[3]}-${match[2].padStart(2, '0')}-${match[1].padStart(2, '0')}`;
}

function formatDateDigits(raw) {
  const digits = String(raw || '').replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return digits.slice(0, 2) + '.' + digits.slice(2);
  return digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4);
}

function isValidEuDate(eu) {
  const match = String(eu || '').match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!match) return false;
  const d = parseInt(match[1], 10);
  const m = parseInt(match[2], 10);
  const y = parseInt(match[3], 10);
  if (m < 1 || m > 12) return false;
  if (d < 1 || d > 31) return false;
  if (y < 1900 || y > 2100) return false;
  return true;
}

export function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function DateInput({ value, onChange, placeholder }) {
  const display = isoToEu(value);
  const [local, setLocal] = useState(display);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    setLocal(isoToEu(value));
  }, [value]);

  function handleChange(e) {
    const formatted = formatDateDigits(e.target.value);
    setLocal(formatted);

    if (/^\d{2}\.\d{2}\.\d{4}$/.test(formatted)) {
      if (isValidEuDate(formatted)) {
        setInvalid(false);
        onChange(euToIso(formatted));
      } else {
        setInvalid(true);
      }
    } else {
      setInvalid(false);
      // Pass empty for incomplete dates — caller decides whether to keep partial
      onChange('');
    }
  }

  return (
    <input
      type="text"
      className={`rp-date-input${invalid ? ' rp-date-invalid' : ''}`}
      value={local}
      onChange={handleChange}
      placeholder={placeholder || 'dd.mm.yyyy'}
    />
  );
}
