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
        // Severity colors for crash data - colorblind-safe palette
        severity: {
          fatal: "#440154",        // Deep Violet
          incapacitating: "#E66100", // Vermillion
          injury: "#56B4E9",       // Sky Blue
          property: "#CCCCCC",     // Light Grey
        },
      },
    },
  },
  plugins: [],
};

export default config;
