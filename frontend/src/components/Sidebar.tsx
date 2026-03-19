import { Link, useLocation } from "react-router-dom";
import { Logo } from "./Logo";
import { useT } from "../hooks/useT";
import { useUIStore } from "../store/uiStore";
import { useSessionStore } from "../store/sessionStore";
import { useTaskStore } from "../store/taskStore";

const navItems = [
  { key: "nav.home", path: "/" },
  { key: "nav.tasks", path: "/tasks" },
  { key: "nav.plugins", path: "/plugins" },
  { key: "nav.documents", path: "/documents" },
  { key: "nav.usage", path: "/usage" },
];

export function Sidebar() {
  const t = useT();
  const { lang, setLang } = useUIStore();
  const location = useLocation();
  const clearSession = useSessionStore((s) => s.clearSession);
  const reset = useTaskStore((s) => s.reset);

  const handleNewChat = () => {
    clearSession();
    reset();
  };

  return (
    <nav className="w-[200px] shrink-0 flex flex-col border-r border-bg-border bg-bg-surface h-screen sticky top-0 py-5 px-3 gap-1">
      {/* Logo + subtitle */}
      <div className="px-2 mb-4">
        <Logo showSubtitle />
      </div>

      {/* New chat */}
      <button
        onClick={handleNewChat}
        className="w-full text-left px-3 py-2 rounded-[6px] text-sm text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors mb-2 flex items-center gap-2"
      >
        <span className="text-primary text-base leading-none">+</span>
        {t("chat.new")}
      </button>

      {/* Nav links */}
      {navItems.map(({ key, path }) => {
        const active = location.pathname === path;
        return (
          <Link
            key={path}
            to={path}
            className={`px-3 py-2 rounded-[6px] text-sm transition-colors ${
              active
                ? "bg-primary/10 text-primary font-medium"
                : "text-text-secondary hover:text-text-primary hover:bg-bg-hover"
            }`}
          >
            {t(key)}
          </Link>
        );
      })}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Settings link */}
      <Link
        to="/settings"
        className={`px-3 py-2 rounded-[6px] text-sm transition-colors ${
          location.pathname === "/settings"
            ? "bg-primary/10 text-primary font-medium"
            : "text-text-secondary hover:text-text-primary hover:bg-bg-hover"
        }`}
      >
        {t("nav.settings")}
      </Link>

      {/* Lang toggle */}
      <button
        onClick={() => setLang(lang === "zh" ? "en" : "zh")}
        className="px-3 py-2 rounded-[6px] text-xs text-text-muted hover:text-text-primary transition-colors text-left"
      >
        {t("lang.switch")}
      </button>
    </nav>
  );
}
