interface LogoProps {
  size?: number;
  showText?: boolean;
  showSubtitle?: boolean;
}

export function Logo({ size = 32, showText = true, showSubtitle = false }: LogoProps) {
  return (
    <div className="flex items-center gap-2.5">
      {/* Three overlapping canopy circles + trunk */}
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <rect width="32" height="32" rx="8" fill="#0d1a0f" />
        {/* left crown */}
        <circle cx="11" cy="13" r="7" fill="#166534" />
        {/* right crown */}
        <circle cx="21" cy="13" r="7" fill="#166534" />
        {/* top crown */}
        <circle cx="16" cy="9" r="7" fill="#22c55e" />
        {/* top-center highlight */}
        <circle cx="16" cy="9" r="4" fill="#4ade80" />
        {/* trunk */}
        <rect x="14.5" y="22" width="3" height="6" rx="1.5" fill="#4ade80" />
      </svg>
      {showText && (
        <div className="flex flex-col">
          <span className="font-semibold tracking-tight text-sm" style={{ color: "#fafafa" }}>
            Canopy <span style={{ color: "#4ade80" }}>Orchestr</span>
          </span>
          {showSubtitle && (
            <span className="text-[10px] text-text-muted leading-tight">
              Multi-LLM Orchestration Platform
            </span>
          )}
        </div>
      )}
    </div>
  );
}
