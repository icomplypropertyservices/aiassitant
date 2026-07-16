/**
 * Canonical agent role helpers — trust API `is_orchestrator` when present.
 */

export function isOrchestrator(a) {
  if (!a) return false
  if (a.is_orchestrator === true) return true
  // Fallback for older payloads
  const role = (a.hierarchy_role || '').toLowerCase()
  const tpl = (a.template_type || '').toLowerCase()
  return role === 'orchestrator' || tpl === 'orchestrator'
}

export function isLead(a) {
  if (!a) return false
  if (isOrchestrator(a)) return true
  return !!(a.is_lead || a.hierarchy_role === 'lead')
}

export function roleLabel(a) {
  if (isOrchestrator(a)) return 'MAIN ORCHESTRATOR'
  if (isLead(a)) return 'Lead'
  if (a?.hierarchy_role === 'specialist') return 'Specialist'
  return 'Member'
}

/** Sort key matching backend: orch → lead → rest */
export function agentSortKey(a) {
  let rank = 2
  if (isOrchestrator(a)) rank = 0
  else if (isLead(a)) rank = 1
  return [rank, (a?.name || '').toLowerCase()]
}

export function sortAgents(list) {
  return [...(list || [])].sort((x, y) => {
    const ax = agentSortKey(x)
    const ay = agentSortKey(y)
    if (ax[0] !== ay[0]) return ax[0] - ay[0]
    return ax[1].localeCompare(ay[1])
  })
}
