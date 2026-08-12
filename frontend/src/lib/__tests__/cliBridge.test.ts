import { describe, expect, it } from 'vitest'
import {
  CLI_BIN,
  COMMON_COMMANDS,
  recipeCliCommand,
  vaultReportCliCommand,
  vaultEvidencePackCliCommand,
} from '../cliBridge'
import type { EvidencePackSummary, RecipeSummary, ReportSummary } from '../api'

describe('cliBridge', () => {
  it('exports the CLI binary name', () => {
    expect(CLI_BIN).toBe('crp-comply')
  })

  it('includes common commands', () => {
    expect(COMMON_COMMANDS.some((c) => c.id === 'report')).toBe(true)
    expect(COMMON_COMMANDS.some((c) => c.id === 'worker')).toBe(true)
  })

  it('builds recipe CLI command', () => {
    const recipe: RecipeSummary = {
      recipe_id: 'eu_ai_act_annex_iv',
      title: 'Annex IV technical documentation',
      regulation: 'EU AI Act',
      description: '',
      required_inputs: [],
      tags: [],
    }
    expect(recipeCliCommand(recipe)).toBe(
      `${CLI_BIN} worker "Generate deliverable: Annex IV technical documentation"`,
    )
  })

  it('escapes quotes in recipe titles', () => {
    const recipe: RecipeSummary = {
      recipe_id: 'x',
      title: 'Doc with "quotes"',
      regulation: 'EU AI Act',
      description: '',
      required_inputs: [],
      tags: [],
    }
    expect(recipeCliCommand(recipe)).toBe(
      `${CLI_BIN} worker "Generate deliverable: Doc with \\"quotes\\""`,
    )
  })

  it('builds report CLI command', () => {
    const report: ReportSummary = {
      id: 'r1',
      kind: 'risk_assessment',
      system_name: 'CRM AI',
      risk_level: 'HIGH',
      tier: 'starter',
      created_at: '',
      size_bytes: 0,
      has_markdown: true,
    }
    expect(vaultReportCliCommand(report)).toBe(`${CLI_BIN} report --format markdown --category risk_assessment`)
  })

  it('builds evidence pack CLI command', () => {
    const report: ReportSummary = {
      id: 'r2',
      kind: 'evidence_pack',
      system_name: 'CRM AI',
      risk_level: null,
      tier: 'starter',
      created_at: '',
      size_bytes: 0,
      has_markdown: true,
    }
    expect(vaultReportCliCommand(report)).toBe(
      `${CLI_BIN} evidence-pack --system-name "CRM AI"`,
    )
  })

  it('builds evidence pack command from summary', () => {
    const pack: EvidencePackSummary = {
      pack_id: 'p1',
      system_name: 'HR Bot',
      category: 'employment',
      tier: 'starter',
      created_at: '',
      file_count: 3,
      zip_bytes: 0,
    }
    expect(vaultEvidencePackCliCommand(pack)).toBe(
      `${CLI_BIN} evidence-pack --system-name "HR Bot"`,
    )
  })
})
