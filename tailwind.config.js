/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: "var(--brand)",
        surface: "#0f172a",
        card: "#1e293b",
        border: "#334155",
        title: "#f8fafc",
        muted: "#94a3b8",
      },
    },
  },
  plugins: [],
};
