/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bmw: {
          blue: '#4599FE',
          navy: '#031E49',
          red: '#EE0405',
          white: '#FFFDFE',
          gunmetal: '#2D4046',
          loblolly: '#B8CAD1',
          gray: '#F0F4F8',
          border: '#B8CAD1',
          text: '#031E49',
        },
      },
    },
  },
  plugins: [],
}
