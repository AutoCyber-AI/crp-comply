"""One-shot script: convert silent except/asserts to logged variants.

Reads `EDITS` (file -> list of (line_number_1based, kind, ...)) and
applies each in place. Designed to be safe: verifies the line at the
expected position matches the expected pattern before editing.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def edit_pass_or_continue(
    path: Path,
    line_no: int,  # 1-based line of the `except Exception:` line
    keyword: str,  # 'pass' or 'continue'
    logger_name: str,
    label: str,
) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    idx = line_no - 1  # 0-based
    # Locate the `except` line within +/- 2 lines tolerance.
    candidates = [i for i in range(max(0, idx - 2), min(len(lines), idx + 3))
                  if lines[i].lstrip().startswith("except ") and lines[i].rstrip().endswith(":")]
    if not candidates:
        print(f"  ! {path.relative_to(ROOT)}:{line_no}: no except line found near anchor")
        return False
    except_idx = min(candidates, key=lambda i: abs(i - idx))
    except_line = lines[except_idx]
    indent = except_line[: len(except_line) - len(except_line.lstrip())]
    body_indent = indent + "    "
    # Walk forward to find the body keyword (allow comment between).
    body_idx = None
    for j in range(except_idx + 1, min(except_idx + 6, len(lines))):
        stripped = lines[j].strip()
        if stripped == keyword:
            body_idx = j
            break
    if body_idx is None:
        print(f"  ! {path.relative_to(ROOT)}:{line_no}: no '{keyword}' body found")
        return False
    # Already remediated?
    if " as _bandit_exc" in except_line:
        print(f"  - {path.relative_to(ROOT)}:{line_no}: already remediated")
        return False
    # Strip an optional `Exception` to confirm it's an unqualified swallow.
    new_except = indent + "except Exception as _bandit_exc:"
    log_line = f'{body_indent}{logger_name}.debug("swallowed in {label}: %s", _bandit_exc)'
    new_lines = lines[:except_idx] + [new_except, log_line] + lines[except_idx + 1 : body_idx + 1] + lines[body_idx + 1 :]
    # Note: we keep the original keyword line intact.
    path.write_text("\n".join(new_lines), encoding="utf-8")
    print(f"  + {path.relative_to(ROOT)}:{line_no}: {keyword} swallow -> logged")
    return True


def edit_assert(path: Path, line_no: int, exc_type: str, message: str) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    idx = line_no - 1
    line = lines[idx]
    stripped = line.lstrip()
    if not stripped.startswith("assert "):
        print(f"  ! {path.relative_to(ROOT)}:{line_no}: not an assert line: {stripped[:60]}")
        return False
    indent = line[: len(line) - len(stripped)]
    cond = stripped[len("assert ") :].split(",", 1)[0].strip()
    new_block = [
        f"{indent}if not ({cond}):",
        f'{indent}    raise {exc_type}("{message}")',
    ]
    new_lines = lines[:idx] + new_block + lines[idx + 1 :]
    path.write_text("\n".join(new_lines), encoding="utf-8")
    print(f"  + {path.relative_to(ROOT)}:{line_no}: assert -> {exc_type}")
    return True


# (file_relpath, line, kind, *args)
# kind = 'pass'|'continue'|'assert'
# pass/continue: (logger_name, label)
# assert: (exc_type, message)
EDITS: list[tuple[str, int, str, tuple]] = [
    # crp_integration.py
    ("src/crp_comply/agent/crp_integration.py", 195, "continue", ("logger", "_extract_sources_from_facts")),
    ("src/crp_comply/agent/crp_integration.py", 497, "continue", ("logger", "_extract_clarifications")),
    ("src/crp_comply/agent/crp_integration.py", 511, "continue", ("logger", "_extract_contradictions")),
    ("src/crp_comply/agent/crp_integration.py", 578, "continue", ("logger", "_extract_quality_issues")),
    # live_regulation.py
    ("src/crp_comply/agent/live_regulation.py", 276, "assert", ("RuntimeError", "expected b and c to be set in diff calculation")),
    # rag/embedder.py — no logger; convert assert
    ("src/crp_comply/agent/rag/embedder.py", 64, "assert", ("RuntimeError", "embedder dimension not initialised")),
    # rag_service.py — no logger; treat as pass with inline logger
    ("src/crp_comply/agent/rag_service.py", 107, "pass", ("__import__('logging').getLogger(__name__)", "rag_service.close")),
    # api/agent.py
    ("src/crp_comply/api/agent.py", 467, "continue", ("logger", "agent_sessions")),
    # draft_sessions.py
    ("src/crp_comply/api/draft_sessions.py", 130, "continue", ("log", "draft_sessions.list")),
    # evidence_signing.py
    ("src/crp_comply/api/evidence_signing.py", 145, "pass", ("log", "_generate_ed25519_seed")),
    # kek.py
    ("src/crp_comply/api/kek.py", 87, "assert", ("ValueError", "KEK version tag must start with 'v'")),
    ("src/crp_comply/api/kek.py", 178, "assert", ("ValueError", "envelope version tag must start with 'v'")),
    # notifications.py
    ("src/crp_comply/api/notifications.py", 51, "assert", ("RuntimeError", "inbox dispatcher not initialised")),
    # provider.py
    ("src/crp_comply/api/provider.py", 166, "pass", ("logger", "provider._encrypt_key (KEK best-effort)")),
    # reports.py
    ("src/crp_comply/api/reports.py", 244, "continue", ("logger", "reports.list_reports")),
    ("src/crp_comply/api/reports.py", 273, "continue", ("logger", "reports.counts")),
    ("src/crp_comply/api/reports.py", 306, "continue", ("logger", "reports.purge_older_than")),
    ("src/crp_comply/api/reports.py", 502, "continue", ("logger", "reports.list_packs")),
    ("src/crp_comply/api/reports.py", 548, "continue", ("logger", "reports.purge_packs_older_than")),
    # routes.py
    ("src/crp_comply/api/routes.py", 742, "pass", ("logger", "manifest (artefact index best-effort)")),
    ("src/crp_comply/api/routes.py", 750, "pass", ("logger", "manifest (proxy stats best-effort)")),
    ("src/crp_comply/api/routes.py", 759, "pass", ("logger", "manifest (corpus manifest best-effort)")),
    ("src/crp_comply/api/routes.py", 1251, "pass", ("logger", "audit_trail_enforcement (CRP integration best-effort)")),
    ("src/crp_comply/api/routes.py", 1373, "pass", ("logger", "ckf_restore (best-effort)")),
    ("src/crp_comply/api/routes.py", 1431, "pass", ("logger", "ckf_persist (best-effort)")),
    ("src/crp_comply/api/routes.py", 1519, "pass", ("logger", "telemetry_read (best-effort)")),
    ("src/crp_comply/api/routes.py", 1568, "pass", ("logger", "emit_event (best-effort)")),
    # sdk.py
    ("src/crp_comply/api/sdk.py", 341, "pass", ("logger", "sdk.features (quota best-effort)")),
    ("src/crp_comply/api/sdk.py", 475, "pass", ("logger", "sdk.audit (quota best-effort)")),
    ("src/crp_comply/api/sdk.py", 699, "pass", ("logger", "sdk.worker (quota best-effort)")),
    # backup.py
    ("src/crp_comply/backup.py", 287, "continue", ("logger", "backup.export_categories (user filter)")),
    ("src/crp_comply/backup.py", 441, "continue", ("logger", "backup.delete_user")),
    # programme/lifecycle.py
    ("src/crp_comply/programme/lifecycle.py", 230, "continue", ("log", "lifecycle.list")),
]


def main() -> None:
    # Process edits per file in REVERSE line order so prior edits don't shift
    # subsequent line numbers within the same file.
    by_file: dict[str, list[tuple[int, str, tuple]]] = {}
    for relpath, line, kind, args in EDITS:
        by_file.setdefault(relpath, []).append((line, kind, args))
    n_ok = 0
    n_total = 0
    for relpath, items in by_file.items():
        path = ROOT / relpath
        print(f"\n== {relpath} ==")
        for line, kind, args in sorted(items, key=lambda t: -t[0]):
            n_total += 1
            if kind == "assert":
                exc_type, msg = args
                if edit_assert(path, line, exc_type, msg):
                    n_ok += 1
            else:
                logger_name, label = args
                if edit_pass_or_continue(path, line, kind, logger_name, label):
                    n_ok += 1
    print(f"\nApplied {n_ok}/{n_total} edits.")


if __name__ == "__main__":
    main()
