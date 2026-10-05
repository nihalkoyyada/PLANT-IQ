/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        scada: {
          bg: "#f0f4fa",
          card: "#ffffff",
          navy: "#004874",
          "navy-dark": "#003354",
          blue: "#0284c7",
          "blue-light": "#e0f2fe",
          emerald: "#10b981",
          "emerald-light": "#d1fae5",
          amber: "#f59e0b",
          "amber-light": "#fef3c7",
          rose: "#ef4444",
          "rose-light": "#fee2e2",
          slate: "#64748b",
          border: "#e2e8f0",
          header: "#f8fafc",
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Monaco', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
