/** AI Guardian mark: a shield holding a small dependency graph, on a white rounded tile. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} role="img" aria-label="AI Architecture Guardian logo">
      <rect width="40" height="40" rx="8" fill="#FFFFFF" />
      <path
        d="M20 8 L28 12 L28 22 C28 28 24 32 20 34 C16 32 12 28 12 22 L12 12 Z"
        fill="none" stroke="#000000" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      />
      <g stroke="#000000" strokeWidth="1">
        <line x1="20" y1="14" x2="16" y2="22" />
        <line x1="20" y1="14" x2="24" y2="22" />
        <line x1="16" y1="22" x2="24" y2="22" />
        <line x1="20" y1="14" x2="20" y2="28" />
      </g>
      <g fill="#000000">
        <circle cx="20" cy="14" r="1.5" />
        <circle cx="16" cy="22" r="1.5" />
        <circle cx="24" cy="22" r="1.5" />
        <circle cx="20" cy="28" r="1.5" />
      </g>
    </svg>
  );
}
