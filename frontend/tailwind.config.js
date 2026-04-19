/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        node: {
          session: '#3B82F6',
          episode: '#8B5CF6',
          theory: '#F59E0B',
          concept: '#10B981',
          pattern: '#EC4899',
          failure: '#EF4444',
          contradiction: '#F97316',
          knowledge: '#06B6D4',
        },
      },
    },
  },
  plugins: [],
};
