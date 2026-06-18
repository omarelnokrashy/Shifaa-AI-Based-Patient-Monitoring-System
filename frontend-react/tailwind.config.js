/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Clinical navy – primary brand, sidebar, dark chrome
        navy: {
          50:  '#f0f4f8',
          100: '#d9e2ec',
          200: '#bcccdc',
          300: '#9fb3c8',
          400: '#829ab1',
          500: '#627d98',
          600: '#486581',
          700: '#334e68',
          800: '#243b53',
          900: '#102a43',
          950: '#0a1929',
        },
        // Teal – primary action / active state
        teal: {
          50:  '#e6fafa',
          100: '#b3f0f0',
          200: '#80e5e5',
          300: '#4ddada',
          400: '#1acfcf',
          500: '#0d9e9e',
          600: '#0d7377',   // ← main brand teal from original design
          700: '#0a5a5d',
          800: '#074143',
          900: '#042829',
        },
        // Alert severity — strict semantic meaning
        alert: {
          critical: '#dc2626',  // red-600
          high:     '#ea580c',  // orange-600
          medium:   '#d97706',  // amber-600
          low:      '#2563eb',  // blue-600
          ok:       '#16a34a',  // green-600
        },
      },
      fontFamily: {
        sans:    ['Inter', 'system-ui', 'sans-serif'],
        heading: ['DM Sans', 'Inter', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card:    '0 1px 3px 0 rgb(0 0 0 / 0.07), 0 1px 2px -1px rgb(0 0 0 / 0.07)',
        modal:   '0 20px 60px -15px rgb(0 0 0 / 0.3)',
        sidebar: '2px 0 8px -2px rgb(0 0 0 / 0.15)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
      },
      keyframes: {
        fadeIn:  { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
  safelist: [
    // Alert severity classes dynamically assembled in code
    { pattern: /bg-alert-(critical|high|medium|low|ok)/ },
    { pattern: /text-alert-(critical|high|medium|low|ok)/ },
    { pattern: /border-alert-(critical|high|medium|low|ok)/ },
    { pattern: /ring-alert-(critical|high|medium|low|ok)/ },
  ],
}
