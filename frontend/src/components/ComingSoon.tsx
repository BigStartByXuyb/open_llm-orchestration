import { useT } from "../hooks/useT";

export function ComingSoon() {
  const t = useT();
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center py-24">
      <div className="w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center">
        <svg
          width="28"
          height="28"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#7c3aed"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <path d="M12 6v6l4 2" />
        </svg>
      </div>
      <div>
        <h2 className="text-lg font-semibold text-text-primary mb-1">
          {t("coming_soon.title")}
        </h2>
        <p className="text-sm text-text-secondary max-w-xs">{t("coming_soon.desc")}</p>
      </div>
    </div>
  );
}
