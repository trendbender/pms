import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // neutral, data-forward palette (light minimal per redesign direction)
        ink: "#0f172a",
        muted: "#64748b",
      },
    },
  },
  plugins: [],
};

export default config;
