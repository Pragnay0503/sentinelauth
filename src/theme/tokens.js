/**
 * SentinelAuth Design System Tokens
 * JavaScript token definitions matching tokens.css.
 */

export const colors = {
  void: '#0B0F14',
  panel: '#141A22',
  panelBorder: '#232B38',
  primaryBlue: '#2D6A9F',
  primaryBlueHover: '#367DBB',
  primaryBlueActive: '#245782',
  signalAmber: '#D9A441',
  alertRed: '#C0392B',
  verifiedGreen: '#3F9868',
  neutralGrey: '#8A93A3',
  ink: '#E4E7EB',
  inkMuted: '#8A93A3',
  panelHover: '#1B222D',
  panelActive: '#202937',
  primaryBlueMuted: 'rgba(45, 106, 159, 0.15)',
  primaryBlueGlow: 'rgba(45, 106, 159, 0.35)',
  signalAmberMuted: 'rgba(217, 164, 65, 0.15)',
  signalAmberGlow: 'rgba(217, 164, 65, 0.35)',
  alertRedMuted: 'rgba(192, 57, 43, 0.15)',
  verifiedGreenMuted: 'rgba(63, 152, 104, 0.15)',
  neutralGreyMuted: 'rgba(138, 147, 163, 0.15)',
};

export const spacing = {
  1: '4px',
  2: '8px',
  3: '12px',
  4: '16px',
  6: '24px',
  8: '32px',
  12: '48px',
  16: '64px',
};

export const radius = {
  control: '4px', // interactive controls only
  panel: '0px',   // structural panels/dividers
};

export const breakpoints = {
  mobile: '640px',   // <640px
  tablet: '1024px',  // 640-1024px
  desktop: '1024px', // >1024px
};

export const typography = {
  fontSans: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontMono: "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
};

export default {
  colors,
  spacing,
  radius,
  breakpoints,
  typography,
};
