import type { CitecheckApi } from '../../../preload/index'

declare global {
  interface Window {
    citecheck: CitecheckApi
  }
}

export {}
