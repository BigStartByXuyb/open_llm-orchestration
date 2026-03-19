import { useUIStore } from "../store/uiStore";
import { t } from "../i18n";

export function useT() {
  const lang = useUIStore((s) => s.lang);
  return (key: string) => t(key, lang);
}
