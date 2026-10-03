/** Every outbound link on the landing page, in one place.
 *  The .dmg name is pinned by build.mac.artifactName in app/package.json,
 *  so /releases/latest/download keeps working across versions. */
const REPO = 'https://github.com/may3rr/citecheck'

export const LINKS = {
  repo: REPO,
  releases: `${REPO}/releases`,
  mac: `${REPO}/releases/latest/download/Clover-mac-arm64.dmg`,
}
