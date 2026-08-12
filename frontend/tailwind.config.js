/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: ['class', '[class~="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        display: ['Space Grotesk', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        // Brand — yellow primary with ink on top
        primary: {
          DEFAULT: 'var(--crp-primary)',
          hover: 'var(--crp-primary-hover)',
          muted: 'var(--crp-primary-muted)',
          ink: 'var(--crp-primary-ink)',
        },
        ink: {
          DEFAULT: 'var(--crp-ink)',
          2: 'var(--crp-ink-2)',
          3: 'var(--crp-ink-3)',
          4: 'var(--crp-ink-4)',
        },
        hairline: 'var(--crp-hairline)',
        surface: {
          DEFAULT: 'var(--crp-surface)',
          2: 'var(--crp-surface-2)',
          3: 'var(--crp-surface-3)',
          inverse: 'var(--crp-surface-inverse)',
        },
        success: {
          DEFAULT: 'var(--crp-success)',
          muted: 'var(--crp-success-muted)',
        },
        warning: {
          DEFAULT: 'var(--crp-warning)',
          muted: 'var(--crp-warning-muted)',
        },
        danger: {
          DEFAULT: 'var(--crp-danger)',
          muted: 'var(--crp-danger-muted)',
        },
        risk: {
          minimal: 'var(--crp-risk-minimal)',
          limited: 'var(--crp-risk-limited)',
          high: 'var(--crp-risk-high)',
          unacceptable: 'var(--crp-risk-unacceptable)',
        },
        // Keep legacy `brand-*` (blue-style ramp) remapped to the new
        // yellow primary so any un-migrated pages still look on-brand.
        brand: {
          50: '#FBFBF5',
          100: '#F4F8DC',
          200: '#EEF5B3',
          300: '#E3EE82',
          400: '#D8E862',
          500: '#D4E84A',
          600: '#C2D541',
          700: '#9DAB34',
          800: '#6F7A25',
          900: '#414716',
          950: '#21250A',
        },
      },
      borderRadius: {
        sm: 'var(--crp-r-sm)',
        md: 'var(--crp-r-md)',
        lg: 'var(--crp-r-lg)',
        xl: 'var(--crp-r-xl)',
      },
      boxShadow: {
        'crp-sm': 'var(--crp-shadow-sm)',
        crp: 'var(--crp-shadow)',
        'crp-lg': 'var(--crp-shadow-lg)',
      },
      transitionTimingFunction: {
        crp: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
      },
      transitionDuration: {
        crp: '180ms',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(16px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        tiltScales: {
          '0%, 100%': { transform: 'rotate(-3deg)' },
          '50%': { transform: 'rotate(3deg)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(194, 213, 65, 0.4)' },
          '50%': { boxShadow: '0 0 20px 4px rgba(194, 213, 65, 0.2)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.92)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        typingDot: {
          '0%, 60%, 100%': { transform: 'translateY(0)' },
          '30%': { transform: 'translateY(-4px)' },
        },
        borderGlow: {
          '0%, 100%': { borderColor: 'rgba(194, 213, 65, 0.3)' },
          '50%': { borderColor: 'rgba(194, 213, 65, 0.8)' },
        },
        countPop: {
          '0%': { transform: 'scale(0.5)', opacity: '0' },
          '70%': { transform: 'scale(1.1)' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        flowArrow: {
          '0%': { opacity: '0.3', transform: 'translateX(-4px)' },
          '50%': { opacity: '1', transform: 'translateX(0)' },
          '100%': { opacity: '0.3', transform: 'translateX(4px)' },
        },
      },
      animation: {
        'fade-in': 'fadeIn 220ms cubic-bezier(0.2,0.8,0.2,1)',
        'slide-up': 'slideUp 260ms cubic-bezier(0.2,0.8,0.2,1)',
        'slide-in-right': 'slideInRight 260ms cubic-bezier(0.2,0.8,0.2,1)',
        'tilt-scales': 'tiltScales 1.8s ease-in-out infinite',
        shimmer: 'shimmer 1.6s linear infinite',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'scale-in': 'scaleIn 200ms cubic-bezier(0.2,0.8,0.2,1)',
        'typing-dot': 'typingDot 1.2s ease-in-out infinite',
        'border-glow': 'borderGlow 2s ease-in-out infinite',
        'count-pop': 'countPop 400ms cubic-bezier(0.2,0.8,0.2,1)',
        'flow-arrow': 'flowArrow 1.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
