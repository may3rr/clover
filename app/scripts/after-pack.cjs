// electron-builder afterPack: ad-hoc sign the whole bundle. The build is
// not notarized; a consistent ad-hoc signature turns macOS's "damaged"
// verdict on downloaded copies into the ordinary "unidentified developer"
// prompt (System Settings > Privacy & Security > Open Anyway).
const { execFileSync } = require('node:child_process')
const path = require('node:path')

exports.default = async function afterPack(ctx) {
  if (ctx.electronPlatformName !== 'darwin') return
  const appPath = path.join(ctx.appOutDir, `${ctx.packager.appInfo.productFilename}.app`)
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' })
}
