import { Routes, Route } from 'react-router-dom';
import TopNav from './components/layout/TopNav';

function MainPage() {
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--doc-bg)',
      color: 'var(--doc-text-2)',
      fontFamily: 'var(--sans)',
    }}>
      <div style={{ textAlign: 'center' }}>
        <h1 style={{ fontSize: 24, fontWeight: 500, color: 'var(--doc-text)', margin: '0 0 8px' }}>
          regpulse
        </h1>
        <p style={{ margin: 0, fontSize: 14 }}>Phase G — Query UI v2</p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="app-shell">
      <div className="main-column">
        <TopNav />
        <Routes>
          <Route path="/" element={<MainPage />} />
        </Routes>
      </div>
    </div>
  );
}
