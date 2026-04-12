import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        panel: 'var(--panel)',
        accent: 'var(--accent)',
        'accent-hover': 'var(--accent-hover)',
        border: 'var(--border)',
        muted: 'var(--muted)',
        fg: 'var(--fg)',
        'fg-secondary': 'var(--fg-secondary)',
      },
    },
  },
  plugins: [],
};

export default config;
