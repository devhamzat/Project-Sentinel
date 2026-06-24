import { THEMES } from "../useTheme.js";

const LABELS = {
  light: "light — minimal white",
  dark: "dark — deep slate",
  mono: "mono — grayscale",
};

export default function Settings({ theme, setTheme }) {
  return (
    <section className="block">
      <h2>settings</h2>
      <div className="setting">
        <div className="setting-label">theme</div>
        <div className="theme-options">
          {THEMES.map((t) => (
            <button
              key={t}
              className={`theme-opt ${theme === t ? "active" : ""}`}
              onClick={() => setTheme(t)}
            >
              <span className={`swatch swatch-${t}`} />
              {LABELS[t]}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
