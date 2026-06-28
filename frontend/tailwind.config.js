/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: '#F4F4F0',
        ink: '#1A1A1A',
        accent: {
          DEFAULT: '#1E3A5A',
          light: '#2E5A8C',
          dark: '#122538',
        },
        teal: {
          DEFAULT: '#0F766E',
          light: '#149E94',
        },
        burgundy: '#7C2D12',
        sage: '#5F6F52',
        warn: '#B91C1C',
        muted: '#5C5C5C',
      },
      fontFamily: {
        serif: ['"Source Serif 4"', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        'brutal': '4px 4px 0px 0px #1A1A1A',
        'brutal-sm': '2px 2px 0px 0px #1A1A1A',
        'brutal-lg': '6px 6px 0px 0px #1A1A1A',
        'brutal-accent': '4px 4px 0px 0px #1E3A5A',
      },
      borderWidth: {
        '3': '3px',
      },
      borderRadius: {
        'brutal': '2px',
      },
    },
  },
  plugins: [],
}
