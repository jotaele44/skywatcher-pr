import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted fonts (bundled) replace the render-blocking Google Fonts @import.
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono'
import App from '@/App.jsx'
import '@/index.css'
// Shared PRII federation design layer, single-sourced from @pr-federation/react
// (replaces the local federation.css copy).
import '@pr-federation/react/styles.css'

// This app commits to its dark radar/command identity. Stamp the shared
// federation.css signals so accent + dark tokens apply across the federation.
document.documentElement.dataset.repo = 'skywatcher-pr'
document.documentElement.dataset.theme = 'dark'

ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
)
