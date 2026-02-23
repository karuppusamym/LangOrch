import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      colors: {
        // Brand
        brand: {
          50:  "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },
        primary: {
          50:  "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },
        // Sidebar
        sidebar: {
          bg:     "#0f172a",
          hover:  "#1e293b",
          active: "#1e3a8a",
          text:   "#94a3b8",
          active_text: "#e2e8f0",
          border: "#1e293b",
        },
        // Tier colors (matching WorkflowBuilder)
        det: {
          DEFAULT: "#3b82f6",
          light: "#eff6ff",
          text: "#1d4ed8",
        },
        intel: {
          DEFAULT: "#7c3aed",
          light: "#f5f3ff",
          text: "#5b21b6",
        },
        ctrl: {
          DEFAULT: "#f97316",
          light: "#fff7ed",
          text: "#c2410c",
        },
        surface: {
          DEFAULT: "#ffffff",
          secondary: "#f8fafc",
          tertiary: "#f1f5f9",
        },
      },
      boxShadow: {
        card:  "0 1px 4px 0 rgba(15,23,42,0.06), 0 2px 8px 0 rgba(15,23,42,0.04)",
        "card-hover": "0 4px 16px 0 rgba(15,23,42,0.1), 0 1px 4px 0 rgba(15,23,42,0.06)",
        modal: "0 20px 60px -10px rgba(15,23,42,0.25)",
      },
      borderRadius: {
        xl2: "1rem",
        xl3: "1.25rem",
      },
    },
  },
  plugins: [],
};

export default config;
