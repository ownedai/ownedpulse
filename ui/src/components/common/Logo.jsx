export default function Logo() {
  return (
    <div className="flex items-center gap-2.5 select-none">
      <svg
        width="28" height="28" viewBox="0 0 28 28" fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <rect x="2" y="2" width="24" height="24" rx="4" stroke="#60A5FA" strokeWidth="2" />
        <circle cx="14" cy="14" r="6" fill="#60A5FA" />
      </svg>
      <span className="text-lg font-semibold tracking-tight">
        <span className="text-[#F8FAFC]">owned</span>
        <span className="text-accent-dark">ai</span>
      </span>
    </div>
  );
}
