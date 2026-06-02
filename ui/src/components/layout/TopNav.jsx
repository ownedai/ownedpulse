import { useLocation } from 'react-router-dom';
import ThemeToggle from '../common/ThemeToggle';

function usePageTitle() {
  const { pathname } = useLocation();
  if (pathname === '/') return null;
  if (pathname === '/history') return 'Query History';
  if (pathname === '/corpus/runs') return 'Run Log';
  if (pathname.startsWith('/corpus/') && pathname.length > '/corpus/'.length) return 'Document Detail';
  if (pathname === '/corpus') return 'Corpus Registry';
  if (pathname === '/admin') return 'Admin';
  if (pathname === '/sources') return 'Sources';
  return null;
}

export default function TopNav() {
  const title = usePageTitle();
  return (
    <nav className="top-nav">
      {title && <span className="top-nav-title">{title}</span>}
      <ThemeToggle />
    </nav>
  );
}
