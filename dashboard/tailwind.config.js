/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: '#111827',   // card bg
        border:  '#1f2937',   // subtle border
      },
    },
  },
  plugins: [],
}
