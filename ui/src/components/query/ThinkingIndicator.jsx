export default function ThinkingIndicator() {
  return (
    <div className="mb-6 flex items-center gap-2 py-2">
      <div className="flex gap-1">
        <div className="w-2 h-2 bg-accent-light rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
        <div className="w-2 h-2 bg-accent-light rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
        <div className="w-2 h-2 bg-accent-light rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
      <span className="text-sm text-secondary">Retrieving and analyzing regulatory documents...</span>
    </div>
  );
}
