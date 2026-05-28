import { Routes, Route } from 'react-router-dom';

export default function App() {
  return (
    <div style={{
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--shell-bg)',
      color: 'var(--shell-muted-text)',
      fontFamily: 'var(--sans)',
    }}>
      <div style={{ textAlign: 'center' }}>
        <h1 style={{ fontSize: 24, fontWeight: 500, color: '#F8FAFC', margin: '0 0 8px' }}>
          regpulse
        </h1>
        <p style={{ margin: 0, fontSize: 14 }}>Phase G — Query UI v2</p>
      </div>
    </div>
  );
}
