import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Chicago flag colors
        chicago: {
          blue: "#b3ddf2",
          red: "#cf142b",
        },
        // Severity colors for crash data
        severity: {
          fatal: "#dc2626",
          incapacitating: "#ea580c",
          injury: "#eab308",
          property: "#22c55e",
        },
      },
    },
  },
  plugins: [],
};

export default config;
