/**
 * GlobalAgentPanel - floating governance assistant on every page.
 *
 * Reuses NoCodeAgentPanel in global mode so the same chat UX is available
 * throughout the app while keeping the No-Code page's contextual variant
 * untouched.
 */
import NoCodeAgentPanel from './NoCodeAgentPanel'

export default function GlobalAgentPanel() {
  return <NoCodeAgentPanel mode="global" />
}
