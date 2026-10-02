import type { Prefs } from '../lib/prefs'
import { displayName } from '../lib/prefs'
import Avatar from './Avatar'

/** Bottom-left account row: avatar + name, opens Settings. */
export default function AccountChip({
  prefs,
  onOpen,
}: {
  prefs: Prefs
  onOpen: () => void
}) {
  return (
    <button className="account-chip" onClick={onOpen}>
      <Avatar prefs={prefs} size={24} />
      <span className="font-normal min-w-0 account-chip-name">
        {displayName(prefs)}
      </span>
    </button>
  )
}
