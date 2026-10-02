/** Tailwind v3 config — layout utilities only. All visual tokens live in
 * src/renderer/src/styles/tokens.css (AGENTS §6). Colors/font-size/
 * font-family/shadows are emptied so utilities can't bypass tokens. */
export default {
  content: ['./src/renderer/index.html', './src/renderer/src/**/*.{ts,tsx}'],
  theme: {
    colors: {},
    fontSize: {},
    fontFamily: {},
    boxShadow: {},
    spacing: {
      0: '0px',
      1: '4px',
      2: '8px',
      3: '12px',
      4: '16px',
      6: '24px',
      8: '32px',
      12: '48px',
    },
    borderRadius: {
      none: '0',
      hl: '4px',
      panel: '12px',
      pill: '980px',
    },
    extend: {},
  },
  corePlugins: {
    borderWidth: false,
    borderColor: false,
    divideWidth: false,
    divideColor: false,
    fontStyle: false,
    textTransform: false,
    textDecoration: false,
    ringWidth: false,
    ringColor: false,
    boxShadow: false,
    preflight: true,
  },
  plugins: [],
}
