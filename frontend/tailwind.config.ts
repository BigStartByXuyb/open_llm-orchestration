import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0a0a0b",
          surface: "#111114",
          elevated: "#0d0d10",
          border: "#1e1e24",
          hover: "#2a2a2e",
        },
        primary: {
          DEFAULT: "#4ade80",
          dim: "#22c55e",
          muted: "#166534",
        },
        accent: {
          DEFAULT: "#7c3aed",
          dim: "#6d28d9",
          muted: "#3b0764",
        },
        text: {
          primary: "#fafafa",
          secondary: "#a1a1aa",
          muted: "#52525b",
        },
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "SF Pro Text", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
