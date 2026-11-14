import forms from '@tailwindcss/forms';

// Design tokens from stitch_zero_mdr_ad_portal_dashboard (DESIGN.md + the two screen mockups).
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#00BAF2',
        'primary-hover': '#009ed1',
        'paytm-navy': '#002970',
        'paytm-navy-dark': '#001d52',
        'navy-deep': '#081e46',
        'paytm-cyan': '#00BAF2',
        'paytm-cyan-dark': '#0099cc',
        'paytm-cyan-light': '#e5f8fe',
        tertiary: '#0F4A8A',
        surface: '#F4F7FB',
        'surface-ice': '#F5F9FD',
        'surface-tint': '#EBF5FC',
        'surface-subtle': '#F8FAFC',
        'surface-high': '#EBF2FA',
        'surface-highest': '#E1EAF5',
        'on-surface': '#002970',
        'on-surface-variant': '#4A628A',
        outline: '#D1DEEC',
        'outline-variant': '#E2ECF7',
        'input-border': '#D3E4F5',
        'success-green': '#00B06F',
        'alert-amber': '#F5A623',
        'error-red': '#E53935',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        'label-sm': ['11px', { lineHeight: '14px', letterSpacing: '0.03em', fontWeight: '600' }],
        'label-md': ['12px', { lineHeight: '16px', letterSpacing: '0.01em', fontWeight: '600' }],
        'label-lg': ['14px', { lineHeight: '20px', fontWeight: '600' }],
        'body-sm': ['12px', { lineHeight: '16px', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'body-lg': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'headline-sm': ['16px', { lineHeight: '22px', fontWeight: '700' }],
        'headline-md': ['20px', { lineHeight: '26px', fontWeight: '700' }],
        'headline-lg': ['26px', { lineHeight: '32px', fontWeight: '800' }],
        'headline-xl': ['34px', { lineHeight: '40px', fontWeight: '800' }],
        'display-lg': ['48px', { lineHeight: '56px', letterSpacing: '-0.02em', fontWeight: '800' }],
        'currency-display': ['40px', { lineHeight: '48px', letterSpacing: '-0.02em', fontWeight: '800' }],
      },
      borderRadius: {
        DEFAULT: '0.375rem',
        lg: '0.5rem',
        xl: '0.75rem',
        '2xl': '1rem',
        full: '9999px',
      },
      boxShadow: {
        ambient: '0 8px 24px -4px rgba(0, 41, 112, 0.08)',
        focus: '0 0 0 3px rgba(0, 186, 242, 0.18)',
      },
      maxWidth: {
        shell: '1680px',
      },
    },
  },
  plugins: [forms],
};
