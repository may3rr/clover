import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import Toast from './screens/Toast'
import { IS_WIN } from './lib/platform'
import { trackCaptionColor } from './lib/caption'
import './styles/tokens.css'
import './styles/base.css'

// Windows overrides in base.css hang off this (no vibrancy, caption buttons)
if (IS_WIN) document.documentElement.dataset.platform = 'win32'
// caption buttons follow the surface under them (not in the toast window)
if (IS_WIN && !location.hash.startsWith('#toast') && window.citecheck?.setCaptionColor) {
  trackCaptionColor(window.citecheck.setCaptionColor)
}

// the bottom-right progress toast loads this same bundle at #toast;
// #toast-demo shows it with sample data in a plain browser tab
const hash = location.hash
const root =
  hash === '#toast' ? (
    <Toast />
  ) : hash === '#toast-demo' ? (
    <Toast
      initial={{
        visible: true,
        step: '正在本机检索被引原文',
        file: '基于深度学习的目标检测研究综述.docx',
        pct: 46,
      }}
    />
  ) : (
    <App />
  )

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{root}</React.StrictMode>
)
