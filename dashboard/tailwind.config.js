/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"Geist Mono Variable"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        // Semantic surface tokens
        surface: {
          root: 'rgb(var(--surface-root) / <alpha-value>)',
          DEFAULT: 'rgb(var(--surface-default) / <alpha-value>)',
          card: 'rgb(var(--surface-card) / <alpha-value>)',
          'card-hover': 'rgb(var(--surface-card-hover) / <alpha-value>)',
          elevated: 'rgb(var(--surface-elevated) / <alpha-value>)',
          input: 'rgb(var(--surface-input) / <alpha-value>)',
        },
        // Semantic border tokens
        border: {
          DEFAULT: 'rgb(var(--border-default) / <alpha-value>)',
          subtle: 'rgb(var(--border-subtle) / <alpha-value>)',
          focus: 'rgb(var(--border-focus) / <alpha-value>)',
        },
        // Semantic text tokens
        content: {
          primary: 'rgb(var(--text-primary) / <alpha-value>)',
          secondary: 'rgb(var(--text-secondary) / <alpha-value>)',
          tertiary: 'rgb(var(--text-tertiary) / <alpha-value>)',
          disabled: 'rgb(var(--text-disabled) / <alpha-value>)',
        },
        // Accent (preserves existing 50-950 scale)
        accent: {
          DEFAULT: 'rgb(var(--accent-500) / <alpha-value>)',
          hover: 'rgb(var(--accent-300) / <alpha-value>)',
          muted: 'rgb(var(--accent-600) / <alpha-value>)',
          dim: 'rgb(var(--accent-500) / 0.12)',
          glow: 'rgb(var(--accent-500) / 0.06)',
          50: 'rgb(var(--accent-50) / <alpha-value>)',
          100: 'rgb(var(--accent-100) / <alpha-value>)',
          200: 'rgb(var(--accent-200) / <alpha-value>)',
          300: 'rgb(var(--accent-300) / <alpha-value>)',
          400: 'rgb(var(--accent-400) / <alpha-value>)',
          500: 'rgb(var(--accent-500) / <alpha-value>)',
          600: 'rgb(var(--accent-600) / <alpha-value>)',
          700: 'rgb(var(--accent-700) / <alpha-value>)',
          800: 'rgb(var(--accent-800) / <alpha-value>)',
          900: 'rgb(var(--accent-900) / <alpha-value>)',
          950: 'rgb(var(--accent-950) / <alpha-value>)',
        },
        // Neutral (preserves existing 50-950 scale)
        neutral: {
          50: 'rgb(var(--neutral-50) / <alpha-value>)',
          100: 'rgb(var(--neutral-100) / <alpha-value>)',
          200: 'rgb(var(--neutral-200) / <alpha-value>)',
          300: 'rgb(var(--neutral-300) / <alpha-value>)',
          400: 'rgb(var(--neutral-400) / <alpha-value>)',
          500: 'rgb(var(--neutral-500) / <alpha-value>)',
          600: 'rgb(var(--neutral-600) / <alpha-value>)',
          700: 'rgb(var(--neutral-700) / <alpha-value>)',
          800: 'rgb(var(--neutral-800) / <alpha-value>)',
          900: 'rgb(var(--neutral-900) / <alpha-value>)',
          950: 'rgb(var(--neutral-950) / <alpha-value>)',
        },
        // Status colors
        success: {
          DEFAULT: '#34d399',
          dim: 'rgba(52, 211, 153, 0.12)',
        },
        warning: {
          DEFAULT: '#fbbf24',
          dim: 'rgba(251, 191, 36, 0.12)',
        },
        danger: {
          DEFAULT: '#f87171',
          dim: 'rgba(248, 113, 113, 0.12)',
        },
        info: {
          DEFAULT: '#60a5fa',
          dim: 'rgba(96, 165, 250, 0.12)',
        },
        // Backward compat
        card: 'rgb(var(--surface-card) / <alpha-value>)',
      },
      borderRadius: {
        xs: '4px',
        sm: '6px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      fontSize: {
        display: ['calc(28px * var(--font-scale, 1))', { lineHeight: '1.2', fontWeight: '700' }],
        h1: ['calc(22px * var(--font-scale, 1))', { lineHeight: '1.3', fontWeight: '700' }],
        h2: ['calc(18px * var(--font-scale, 1))', { lineHeight: '1.3', fontWeight: '600' }],
        h3: ['calc(16px * var(--font-scale, 1))', { lineHeight: '1.4', fontWeight: '600' }],
        h4: ['calc(14px * var(--font-scale, 1))', { lineHeight: '1.4', fontWeight: '600' }],
        body: ['calc(14px * var(--font-scale, 1))', { lineHeight: '1.5' }],
        compact: ['calc(13px * var(--font-scale, 1))', { lineHeight: '1.5' }],
        caption: ['calc(12px * var(--font-scale, 1))', { lineHeight: '1.4' }],
        micro: ['calc(11px * var(--font-scale, 1))', { lineHeight: '1.3' }],
        mono: ['calc(13px * var(--font-scale, 1))', { lineHeight: '1.4' }],
        'mono-sm': ['calc(11px * var(--font-scale, 1))', { lineHeight: '1.3' }],
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,0.05)',
        md: '0 4px 12px rgba(0,0,0,0.08)',
        lg: '0 8px 24px rgba(0,0,0,0.12)',
        glow: '0 0 20px rgb(var(--accent-500) / 0.06)',
        'dark-sm': '0 1px 2px rgba(0,0,0,0.3)',
        'dark-md': '0 4px 12px rgba(0,0,0,0.4)',
        'dark-lg': '0 8px 24px rgba(0,0,0,0.5)',
      },
      transitionDuration: {
        fast: '150ms',
        normal: '200ms',
        slow: '300ms',
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'shimmer': 'shimmer 1.5s ease-in-out infinite',
        'slide-in-right': 'slideInRight 200ms ease',
        'slide-out-right': 'slideOutRight 200ms ease',
        'fade-in': 'fadeIn 150ms ease',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        slideOutRight: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(100%)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
