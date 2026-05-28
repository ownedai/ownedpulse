import Logo from '../common/Logo';
import ThemeToggle from '../common/ThemeToggle';

export default function TopNav() {
  return (
    <nav className="top-nav">
      <Logo showWordmark />
      <ThemeToggle />
    </nav>
  );
}
