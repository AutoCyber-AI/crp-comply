# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply CLI — command-line interface for AI governance."""

from __future__ import annotations

import json

import click

from crp_comply.core import CRPComply


@click.group()
def main():
    """CRP Comply — AI Governance & EU AI Act Compliance."""


@main.command("serve")
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", default=8400, type=int, help="Port to listen on.")
@click.option("--reload", "do_reload", is_flag=True, help="Enable auto-reload for development.")
def comply_serve(host, port, do_reload):
    """Start the CRP Comply API server."""
    import uvicorn

    click.echo(f"\n🚀 Starting CRP Comply on {host}:{port}")
    click.echo(f"   Docs: http://{host}:{port}/api/docs\n")
    uvicorn.run(
        "crp_comply.api.app:create_app",
        host=host,
        port=port,
        reload=do_reload,
        factory=True,
    )


@main.command("report")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--category", default="context_management", help="AI system category for risk assessment."
)
def comply_report(fmt, category):
    """Generate EU AI Act + ISO 42001 compliance status report."""
    c = CRPComply()
    assessment = c.assess_risk(category=category, processes_personal_data=True)
    if fmt == "markdown":
        click.echo(c.compliance_report_markdown(risk_assessment=assessment))
    else:
        click.echo(json.dumps(c.compliance_report(risk_assessment=assessment), indent=2))


@main.command("risk-assess")
@click.option(
    "--category",
    default="context_management",
    help="AI system category (e.g. healthcare, financial, employment).",
)
@click.option("--personal-data", is_flag=True, help="System processes personal data.")
@click.option("--automated-decisions", is_flag=True, help="System makes automated decisions.")
@click.option("--fundamental-rights", is_flag=True, help="Affects fundamental rights.")
@click.option("--safety-critical", is_flag=True, help="Safety-critical system.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def comply_risk_assess(
    category, personal_data, automated_decisions, fundamental_rights, safety_critical, as_json
):
    """Run EU AI Act risk assessment (Art. 6) for your AI system."""
    c = CRPComply()
    a = c.assess_risk(
        category=category,
        processes_personal_data=personal_data,
        makes_automated_decisions=automated_decisions,
        affects_fundamental_rights=fundamental_rights,
        safety_critical=safety_critical,
    )
    if as_json:
        click.echo(json.dumps(a.to_dict(), indent=2))
    else:
        risk_icon = {"minimal": "🟢", "limited": "🟡", "high": "🔴", "unacceptable": "⛔"}.get(
            a.risk_level.value, "❓"
        )
        click.echo(f"\n{risk_icon}  Risk Level: {a.risk_level.value.upper()}")
        click.echo(f"   Category:  {a.system_category.value}")
        click.echo(f"\n   Mitigations ({len(a.mitigations)} CRP-native):")
        for m in a.mitigations[:5]:
            click.echo(f"     ✅ {m}")
        if len(a.mitigations) > 5:
            click.echo(f"     ... and {len(a.mitigations) - 5} more")
        if a.residual_risks:
            click.echo("\n   Residual Risks:")
            for r in a.residual_risks:
                click.echo(f"     ⚠  {r}")


@main.command("dpia")
@click.option("--system-name", default="CRP-powered AI System", help="Name of the AI system.")
@click.option("--data-subjects", default="end users", help="Who the data subjects are.")
@click.option("--category", default="context_management", help="AI system category.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown"]),
    default="markdown",
    help="Output format.",
)
def comply_dpia(system_name, data_subjects, category, fmt):
    """Generate DPIA (Data Protection Impact Assessment) — GDPR Art. 35."""
    c = CRPComply()
    dpia = c.generate_dpia(
        system_name=system_name,
        data_subjects=data_subjects,
        category=category,
    )
    if fmt == "markdown":
        click.echo(dpia.to_markdown())
    else:
        click.echo(json.dumps(dpia.to_dict(), indent=2, default=str))


@main.command("transparency")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def comply_transparency(as_json):
    """Generate EU AI Act Art. 13 transparency declaration."""
    c = CRPComply()
    td = c.transparency_declaration()
    if as_json:
        click.echo(json.dumps(td, indent=2, default=str))
    else:
        click.echo("\n📋 Transparency Declaration — EU AI Act Art. 13\n")
        click.echo(f"  System:  {td['system_name']}")
        click.echo(f"  Provider: {td['provider']}")
        click.echo(f"  Risk Level: {td['risk_level']}")
        click.echo(f"\n  Purpose:\n    {td['intended_purpose']}")
        click.echo(f"\n  AI Involvement:\n    {td['ai_involvement']}")
        click.echo("\n  Data Processed:")
        for d in td["data_processed"]:
            click.echo(f"    • {d}")
        click.echo("\n  Data NOT Processed:")
        for d in td["data_not_processed"]:
            click.echo(f"    • {d}")
        click.echo("\n  Limitations:")
        for l in td["limitations"]:
            click.echo(f"    ⚠ {l}")
        click.echo(f"\n  Human Oversight:\n    {td['human_oversight']}")


@main.command("technical-docs")
@click.option("--category", default="context_management", help="AI system category.")
def comply_technical_docs(category):
    """Generate EU AI Act Art. 11 technical documentation (JSON)."""
    c = CRPComply()
    a = c.assess_risk(category=category)
    doc = c.technical_documentation(risk_assessment=a)
    click.echo(json.dumps(doc, indent=2, default=str))


@main.command("audit")
@click.argument("session_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown"]),
    default="markdown",
    help="Output format.",
)
def comply_audit(session_file, fmt):
    """Audit a persisted session file for compliance."""
    c = CRPComply()
    report = c.audit_session(session_file=session_file)
    if fmt == "markdown":
        click.echo(report.to_markdown())
    else:
        click.echo(json.dumps(report.to_dict(), indent=2, default=str))


@main.command("evidence-pack")
@click.option("--system-name", default="CRP-powered AI System", help="Name of the AI system.")
@click.option("--category", default="context_management", help="AI system category.")
@click.option(
    "--session-file",
    default=None,
    type=click.Path(exists=True),
    help="Optional session file to include in evidence.",
)
@click.option("--output", "output_file", default=None, help="Save evidence pack to file.")
def comply_evidence_pack(system_name, category, session_file, output_file):
    """Generate complete conformity evidence pack for regulators."""
    c = CRPComply()
    pack = c.conformity_evidence_pack(
        system_name=system_name,
        category=category,
        session_file=session_file,
    )
    output = json.dumps(pack, indent=2, default=str)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
        click.echo(f"Evidence pack saved to {output_file}")
    else:
        click.echo(output)


@main.command("worker")
@click.argument("task", nargs=-1, required=True)
@click.option("--system-id", default="", help="System identifier for tenancy.")
@click.option("--customer-id", default="", help="Customer identifier for tenancy.")
@click.option("--extra-context", default="", help="Additional context string.")
@click.option("--max-iters", default=8, type=int, help="LLM iteration cap.")
@click.option(
    "--clarification-budget",
    default=6,
    type=int,
    help="Maximum clarification rounds before auto-finalize.",
)
@click.option(
    "--max-continuation-windows",
    default=4,
    type=int,
    help="Maximum continuation windows for length-truncated outputs.",
)
@click.option(
    "--no-pii-redaction",
    is_flag=True,
    help="Disable automatic PII redaction before LLM (NOT recommended).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown", "text"]),
    default="markdown",
    help="Output format.",
)
def comply_worker(
    task,
    system_id,
    customer_id,
    extra_context,
    max_iters,
    clarification_budget,
    max_continuation_windows,
    no_pii_redaction,
    fmt,
):
    """Run a compliance agent task headlessly (Mode C).

    Example:

        comply worker --system-id crm-ai "Assess EU AI Act risk level for our
        CRM lead-scoring model, including Annex III check."

    The command runs the tool-using agent loop to completion (or until the
    clarification budget is exhausted), prints the final answer, and
    reports a summary of iterations, tool calls, PII redactions, and
    continuation windows used.
    """
    from .agent import ComplianceAgent, ComplianceLLM, default_registry
    from .agent.rag_service import RagService

    task_str = " ".join(task).strip()
    if not task_str:
        raise click.UsageError("Task must not be empty.")

    try:
        llm = ComplianceLLM()
    except RuntimeError as exc:
        raise click.ClickException(
            f"No LLM provider configured: {exc}. Set CRP_COMPLY_LLM_BASE_URL, "
            "OPENAI_API_KEY, or ANTHROPIC_API_KEY."
        ) from exc

    rag = None
    try:
        rag = RagService()
    except Exception as exc:
        click.echo(f"[worker] RAG unavailable: {exc}", err=True)

    registry = default_registry(rag=rag, fabric=None)
    agent = ComplianceAgent(
        llm=llm,
        fabric=None,
        tools=registry,
        max_iters=int(max_iters),
        max_clarifications=int(clarification_budget),
        redact_pii_pre_llm=not no_pii_redaction,
        continue_on_length=True,
        max_continuation_windows=int(max_continuation_windows),
    )

    result = agent.run(
        task_str,
        system_id=system_id,
        customer_id=customer_id,
        extra_context=extra_context,
    )

    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return
    if fmt == "text":
        click.echo(result.final_text or f"[state={result.state}] {result.pending_question}")
        return
    # markdown
    click.echo("# Compliance Worker Result\n")
    click.echo(f"- **State:** `{result.state}`")
    click.echo(f"- **Iterations:** {result.iterations} / {max_iters}")
    click.echo(f"- **Tool calls:** {result.tool_calls}")
    click.echo(
        f"- **Clarifications:** {result.clarifications_used} / {result.clarification_budget}"
    )
    click.echo(f"- **PII spans redacted:** {result.pii_redactions}")
    if result.continuation_windows > 1:
        click.echo(
            f"- **Continuation windows:** {result.continuation_windows} "
            f"({result.continuation_reason})"
        )
    click.echo()
    if result.state == "awaiting_clarification":
        click.echo(f"## Pending Question\n\n> {result.pending_question}")
    elif result.state == "done":
        click.echo("## Final Answer\n")
        click.echo(result.final_text)
    elif result.error:
        click.echo(f"## Error\n\n```\n{result.error}\n```")


# ─── Backup / DR / GDPR self-service ────────────────────────────────────


@main.command("export-user")
@click.argument("user_id")
@click.option(
    "--out",
    "out_path",
    default=None,
    type=click.Path(),
    help="Destination .tar.gz path. Defaults to "
    "$CRP_COMPLY_DATA_DIR/exports/{user}-{timestamp}.tar.gz.",
)
def comply_export_user(user_id, out_path):
    """Export every byte the platform stores about USER_ID (GDPR Art. 20)."""
    from crp_comply.backup import export_user

    summary = export_user(user_id, dest=out_path)
    click.echo(json.dumps(summary.as_dict(), indent=2))


@main.command("delete-user")
@click.argument("user_id")
@click.option(
    "--no-cascade",
    is_flag=True,
    help="Only remove auth row + api_keys (account suspension); "
    "leaves reports/evidence/etc untouched.",
)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def comply_delete_user(user_id, no_cascade, yes):
    """Erase every byte the platform stores about USER_ID (GDPR Art. 17)."""
    from crp_comply.backup import delete_user

    if not yes:
        click.confirm(
            f"This will permanently delete every artefact for user {user_id!r}. Continue?",
            abort=True,
        )
    summary = delete_user(user_id, cascade=not no_cascade)
    click.echo(json.dumps(summary.as_dict(), indent=2))


@main.command("backup-all")
@click.argument("dest_path", type=click.Path())
def comply_backup_all(dest_path):
    """Tar+gzip the entire data directory to DEST_PATH for disaster recovery."""
    from crp_comply.backup import backup_all

    summary = backup_all(dest_path)
    click.echo(json.dumps(summary.as_dict(), indent=2))


@main.command("backup-nightly")
def comply_backup_nightly():
    """One-shot nightly DR backup: archive → upload → prune.

    Thin wrapper over :func:`crp_comply.backup_scheduler.run_backup_once`
    so the same code path serves both the in-process scheduler (default,
    runs inside the API service) and ad-hoc ops invocations.

    See ``crp_comply/backup_scheduler.py`` for the env-var contract.
    """
    from crp_comply.backup_scheduler import run_backup_once

    try:
        result = run_backup_once()
    except Exception as exc:
        click.echo(f"[backup-nightly] FAILED: {exc}", err=True)
        raise SystemExit(2)
    click.echo(json.dumps(result, indent=2, default=str))
    click.echo("[backup-nightly] done")


@main.command("restore")
@click.argument("src_path", type=click.Path(exists=True))
@click.option(
    "--overwrite", is_flag=True, help="Replace files that already exist on the live volume."
)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def comply_restore(src_path, overwrite, yes):
    """Restore a backup-all or export-user tarball into the live data dir."""
    from crp_comply.backup import restore

    if not yes and overwrite:
        click.confirm(
            "--overwrite will replace existing files in $CRP_COMPLY_DATA_DIR. Continue?",
            abort=True,
        )
    summary = restore(src_path, overwrite=overwrite)
    click.echo(json.dumps(summary.as_dict(), indent=2))


@main.command("restore-user")
@click.argument("src_path", type=click.Path(exists=True))
@click.option("--user", "user_id", required=True, help="user_id whose data to restore")
@click.option(
    "--overwrite", is_flag=True, help="Replace existing files for this user on the live volume."
)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def comply_restore_user(src_path, user_id, overwrite, yes):
    """Restore one user's data from a backup-all tarball.

    Account-scoped JSON files (users.json, api_keys.json, …) are
    *merged* — only the target user's slice is overlaid; rows for
    other users are preserved bit-for-bit.
    """
    from crp_comply.backup import restore_user

    if not yes:
        click.confirm(
            f"Restore data for user {user_id!r} from {src_path}? "
            "Other users on this volume will be untouched.",
            abort=True,
        )
    summary = restore_user(src_path, user_id, overwrite=overwrite)
    click.echo(json.dumps(summary.as_dict(), indent=2))


@main.command("check-sidecar")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON instead of a human report.",
)
def comply_check_sidecar(as_json):
    """Probe the crp-comply-search sidecar for connectivity + auth.

    Reads ``CRP_COMPLY_SEARCH_URL`` and ``CRP_COMPLY_SEARCH_API_KEY``
    from the environment. Calls ``GET /health`` then a one-shot
    ``POST /search`` so trust-tier filtering and the bearer auth
    pipeline are both exercised. Exits non-zero on any failure so
    the command is safe to chain in CI.
    """
    from crp_comply.sidecar_client import self_check

    report = self_check()
    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
        raise SystemExit(0 if report["ok"] else 1)

    click.echo("")
    click.echo(f"  sidecar URL : {report['base_url']}")
    click.echo(f"  auth        : {report['auth']}")
    if report.get("health"):
        h = report["health"]
        click.echo(
            f"  health      : ok (backend={h.get('backend')!r} "
            f"profile={h.get('profile')!r} version={h.get('version')!r})"
        )
    else:
        click.echo("  health      : FAIL")
    if report.get("search") is not None:
        s = report["search"]
        hits = s.get("hits") or []
        click.echo(f"  search      : ok ({len(hits)} hit(s) returned)")
    else:
        click.echo("  search      : FAIL")
    click.echo(f"  elapsed_ms  : {report.get('elapsed_ms', 0):.1f}")
    for err in report.get("errors", []):
        click.echo(f"  error       : {err}", err=True)
    click.echo("")
    if report["ok"]:
        click.echo("✓ sidecar reachable and serving search results.")
        raise SystemExit(0)
    click.echo("✗ sidecar self-check failed — see error(s) above.", err=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
