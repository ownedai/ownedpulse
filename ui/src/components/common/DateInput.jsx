import { useState, useEffect, useRef, useCallback } from 'react';

function euToIso(d, m, y) {
  return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
}

function isValidDay(d) {
  return /^(0[1-9]|[12]\d|3[01])$/.test(d);
}
function isValidMonth(m) {
  return /^(0[1-9]|1[0-2])$/.test(m);
}
function isValidYear(y) {
  return /^(19|20)\d{2}$/.test(y);
}

function isValidDate(d, m, y) {
  if (!isValidDay(d) || !isValidMonth(m) || !isValidYear(y)) return false;
  const days = new Date(parseInt(y), parseInt(m), 0).getDate();
  return parseInt(d) <= days;
}

function segmentDigits(raw, max) {
  return raw.replace(/\D/g, '').slice(0, max);
}

export function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function DateInput({ value, onChange }) {
  const [day, setDay] = useState('');
  const [month, setMonth] = useState('');
  const [year, setYear] = useState('');
  const [invalidDay, setInvalidDay] = useState(false);
  const [invalidMonth, setInvalidMonth] = useState(false);
  const [invalidYear, setInvalidYear] = useState(false);

  const dayRef = useRef(null);
  const monthRef = useRef(null);
  const yearRef = useRef(null);

  // Sync from parent ISO value
  useEffect(() => {
    if (!value) { setDay(''); setMonth(''); setYear(''); return; }
    const parts = String(value).split('-');
    if (parts.length === 3) {
      setDay(parts[2]);
      setMonth(parts[1]);
      setYear(parts[0]);
      setInvalidDay(false);
      setInvalidMonth(false);
      setInvalidYear(false);
    }
  }, [value]);

  const tryPropagate = useCallback((nd, nm, ny) => {
    if (nd === '' && nm === '' && ny === '') {
      onChange('');
      return;
    }
    if (nd.length === 2 && nm.length === 2 && ny.length === 4) {
      if (isValidDate(nd, nm, ny)) {
        setInvalidDay(false); setInvalidMonth(false); setInvalidYear(false);
        onChange(euToIso(nd, nm, ny));
      } else {
        if (!isValidDay(nd)) setInvalidDay(true); else setInvalidDay(false);
        if (!isValidMonth(nm)) setInvalidMonth(true); else setInvalidMonth(false);
        if (!isValidYear(ny)) setInvalidYear(true); else setInvalidYear(false);
      }
    }
  }, [onChange]);

  function handleDayChange(e) {
    const val = segmentDigits(e.target.value, 2);
    setDay(val);
    if (val.length === 2) {
      if (isValidDay(val)) { setInvalidDay(false); monthRef.current?.focus(); }
      else { setInvalidDay(true); }
    } else {
      setInvalidDay(false);
    }
    tryPropagate(val, month, year);
  }

  function handleMonthChange(e) {
    const val = segmentDigits(e.target.value, 2);
    setMonth(val);
    if (val.length === 2) {
      if (isValidMonth(val)) { setInvalidMonth(false); yearRef.current?.focus(); }
      else { setInvalidMonth(true); }
    } else {
      setInvalidMonth(false);
    }
    tryPropagate(day, val, year);
  }

  function handleYearChange(e) {
    const val = segmentDigits(e.target.value, 4);
    setYear(val);
    if (val.length === 4) {
      if (isValidYear(val)) setInvalidYear(false);
      else setInvalidYear(true);
    } else {
      setInvalidYear(false);
    }
    tryPropagate(day, month, val);
  }

  function handleDayKeyDown(e) {
    if (e.key === 'Backspace' && day === '' && e.target.selectionStart === 0) {
      // already at start of day, nothing to do
    }
    if (e.key === 'ArrowRight' && e.target.selectionStart === day.length) {
      monthRef.current?.focus();
    }
  }

  function handleMonthKeyDown(e) {
    if (e.key === 'Backspace' && month === '' && e.target.selectionStart === 0) {
      dayRef.current?.focus();
      dayRef.current?.setSelectionRange(day.length, day.length);
    }
    if (e.key === 'ArrowRight' && e.target.selectionStart === month.length) {
      yearRef.current?.focus();
    }
    if (e.key === 'ArrowLeft' && e.target.selectionStart === 0) {
      dayRef.current?.focus();
      dayRef.current?.setSelectionRange(day.length, day.length);
    }
  }

  function handleYearKeyDown(e) {
    if (e.key === 'Backspace' && year === '' && e.target.selectionStart === 0) {
      monthRef.current?.focus();
      monthRef.current?.setSelectionRange(month.length, month.length);
    }
    if (e.key === 'ArrowLeft' && e.target.selectionStart === 0) {
      monthRef.current?.focus();
      monthRef.current?.setSelectionRange(month.length, month.length);
    }
  }

  const anyInvalid = invalidDay || invalidMonth || invalidYear;

  function segCls(extra) {
    return `rp-date-input rp-date-seg ${extra}`;
  }

  return (
    <div className={`rp-date-input-group${anyInvalid ? ' rp-date-invalid' : ''}`}>
      <input
        ref={dayRef}
        type="text"
        className={segCls('rp-date-seg-day')}
        value={day}
        onChange={handleDayChange}
        onKeyDown={handleDayKeyDown}
        placeholder="DD"
        maxLength={2}
        inputMode="numeric"
      />
      <span className="rp-date-dot">.</span>
      <input
        ref={monthRef}
        type="text"
        className={segCls('rp-date-seg-month')}
        value={month}
        onChange={handleMonthChange}
        onKeyDown={handleMonthKeyDown}
        placeholder="MM"
        maxLength={2}
        inputMode="numeric"
      />
      <span className="rp-date-dot">.</span>
      <input
        ref={yearRef}
        type="text"
        className={segCls('rp-date-seg-year')}
        value={year}
        onChange={handleYearChange}
        onKeyDown={handleYearKeyDown}
        placeholder="YYYY"
        maxLength={4}
        inputMode="numeric"
      />
    </div>
  );
}
