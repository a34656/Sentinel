import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: ['class'],
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
        sans: ['DM Sans', 'system-ui', 'sans-serif'],
        display: ['Syne', 'sans-serif'],
      },
      colors: {
        bg: {
          base:        '#07090D',
          surface:     '#0C1018',
          elevated:    '#111822',
          border:      '#1A2535',
          borderHover: '#253548',
        },
        cyan:   { DEFAULT: '#00D4FF', dim: '#00D4FF1A', glow: '#00D4FF44' },
        green:  { DEFAULT: '#00FF88', dim: '#00FF881A', glow: '#00FF8844' },
        amber:  { DEFAULT: '#FFB020', dim: '#FFB0201A', glow: '#FFB02044' },
        red:    { DEFAULT: '#FF4444', dim: '#FF44441A', glow: '#FF444444' },
        purple: { DEFAULT: '#A855F7', dim: '#A855F71A', glow: '#A855F744' },
        txt: {
          primary:   '#EAF4FD',
          secondary: '#7BA3BF',
          muted:     '#3A5570',
          code:      '#00D4FF',
        },
      },
      animation: {
        'pulse-dot': 'pulseDot 1.8s ease-in-out infinite',
        'slide-up':  'slideUp 0.25s ease-out',
        'fade-in':   'fadeIn 0.3s ease-out',
        'bar-grow':  'barGrow 0.6s ease-out',
      },
      keyframes: {
        pulseDot: {
          '0%,100%': { opacity: '1', transform: 'scale(1)' },
          '50%':     { opacity: '0.4', transform: 'scale(0.85)' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        barGrow: {
          from: { width: '0%' },
          to:   { width: 'var(--bar-w)' },
        },
      },
    },
  },
  plugins: [],
}
export default config
