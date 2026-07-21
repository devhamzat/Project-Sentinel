import { useEffect, useState } from "react";

export const THEMES = ["watchtower", "light", "dark", "mono"];
const KEY = "smart-extract-theme-v2"; // v2: "watchtower" became the default

// Persisted theme hook. Applies data-theme on <html> so CSS variables switch.
export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem(KEY) || "watchtower");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);

  return [theme, setTheme];
}
