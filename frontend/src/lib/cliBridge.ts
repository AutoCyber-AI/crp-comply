/**
 * CLI-to-web bridge — reusable CRP Comply shell commands.
 *
 * Maps web destinations and entities to the equivalent `crp-comply`
 * terminal invocation so power users can copy a command and continue
 * in their shell.
 */

import type { EvidencePackSummary, RecipeSummary, ReportSummary } from './api'

export const CLI_BIN = 'crp-comply'

export interface CliCommand {
  id: string
  label: string
  command: string
  description: string
}

export const COMMON_COMMANDS: CliCommand[] = [
  {
    id: 'report',
    label: 'Compliance report',
    command: `${CLI_BIN} report --format markdown`,
    description: 'Generate an EU AI Act + ISO 42001 compliance status report.',
  },
  {
    id: 'risk-assess',
    label: 'Risk assessment',
    command: `${CLI_BIN} risk-assess --category context_management`,
    description: 'Run an EU AI Act Art. 6 risk assessment for your system.',
  },
  {
    id: 'dpia',
    label: 'DPIA',
    command: `${CLI_BIN} dpia --system-name "My AI System"`,
    description: 'Generate a GDPR Art. 35 Data Protection Impact Assessment.',
  },
  {
    id: 'transparency',
    label: 'Transparency declaration',
    command: `${CLI_BIN} transparency`,
    description: 'Generate an EU AI Act Art. 13 transparency declaration.',
  },
  {
    id: 'technical-docs',
    label: 'Technical documentation',
    command: `${CLI_BIN} technical-docs --category context_management`,
    description: 'Generate EU AI Act Art. 11 technical documentation (JSON).',
  },
  {
    id: 'evidence-pack',
    label: 'Evidence pack',
    command: `${CLI_BIN} evidence-pack --system-name "My AI System"`,
    description: 'Produce a signed conformity evidence pack for regulators.',
  },
  {
    id: 'worker',
    label: 'Headless compliance worker',
    command: `${CLI_BIN} worker "Assess EU AI Act risk for my system"`,
    description: 'Run the agent loop headlessly from the terminal.',
  },
  {
    id: 'serve',
    label: 'Start local server',
    command: `${CLI_BIN} serve --port 8400`,
    description: 'Start the CRP Comply API server locally.',
  },
]

export function recipeCliCommand(recipe: RecipeSummary): string {
  return `${CLI_BIN} worker "Generate deliverable: ${escapeShell(recipe.title)}"`
}

export function vaultReportCliCommand(report: ReportSummary): string {
  if (report.kind === 'evidence_pack') {
    return `${CLI_BIN} evidence-pack --system-name "${escapeShell(report.system_name || 'My AI System')}"`
  }
  return `${CLI_BIN} report --format markdown --category ${escapeShell(report.kind)}`
}

export function vaultEvidencePackCliCommand(pack: EvidencePackSummary): string {
  return `${CLI_BIN} evidence-pack --system-name "${escapeShell(pack.system_name || 'My AI System')}"`
}

function escapeShell(value: string): string {
  return value.replace(/"/g, '\\"')
}
