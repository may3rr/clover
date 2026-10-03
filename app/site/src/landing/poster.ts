import '../../../src/renderer/src/styles/tokens.css'
import './landing.css'
import './poster.css'

// one live app window, scaled to its box, like the landing page's
const box = document.querySelector<HTMLElement>('.window')!
const f = document.createElement('iframe')
f.src = box.dataset.src!
f.setAttribute('scrolling', 'no')
box.appendChild(f)
box.style.setProperty('--s', String(box.clientWidth / 1280))
addEventListener('message', (e) => {
  if (e.data?.clover === 'ready') box.classList.add('ready')
})
