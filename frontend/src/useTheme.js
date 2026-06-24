import { useEffect, useState } from "react";

export const THEMES = ["light", "dark", "mono"];
const KEY = "smart-extract-theme";

// Persisted theme hook. Applies data-theme on <html> so CSS variables switch.
export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem(KEY) || "light");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);

  return [theme, setTheme];
}
