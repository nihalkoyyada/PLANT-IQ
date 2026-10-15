#!/usr/bin/env python3
"""PlantIQ Copilot Evaluation Harness & CI Pass-Rate Pipeline Runner (§10.5, Task S5-AI-04).

Executes the automated evaluation suite across the 100 golden test cases, computing:
1. Numeric-exact pass rates against ground-truth SCADA metrics (with configurable tolerance).
2. Tool selection routing accuracy.
3. Citation tagging compliance ([T1], [T2], ...).
4. Executive Markdown and machine-readable JSON pass-rate reports.
5. Strict CI Quality Gate enforcement (exits 0 if pass_rate >= threshold, 1 if below).

Usage:
    # 1. CI Quality Gate Mode (Deterministic high-speed offline verification, target >= 80%):
    python backend/scripts/run_copilot_eval.py --threshold 80.0

    # 2. Live LLM Evaluation (Requires ANTHROPIC_API_KEY):
    python backend/scripts/run_copilot_eval.py --provider live --threshold 80.0

    # 3. Custom Output Paths:
    python backend/scripts/run_copilot_eval.py --report-path docs/copilot-eval-report.md --json-output docs/copilot-eval-summary.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Optional
from uuid import UUID, uuid4

# Ensure project root is in sys.path
_script_dir = Path(__file__).resolve().parent
_backend_dir = _script_dir.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

from app.copilot.context import ToolSecurityContext
from app.copilot.eval_dataset import (
    GoldenTestCase,
    generate_golden_dataset,
    load_golden_dataset_from_file,
    save_golden_dataset_to_file,
)
from app.copilot.eval_harness import (
    CIEvaluationProvider,
    CopilotEvaluator,
    EvaluationSummary,
)
from app.copilot.orchestrator import CopilotOrchestrator
from app.db.database import SessionLocal
from app.models.entities import Organization, Plant, User

app = typer.Typer(
    name="run-copilot-eval",
    help="PlantIQ Copilot Automated Evaluation Harness & Quality Gate Runner",
)
console = Console()


def _get_or_create_eval_context(db) -> ToolSecurityContext:
    """Retrieve or configure a valid multi-tenant security context for evaluation."""
    # Look for existing Surya-A plant or fallback to primary plant
    plant = db.query(Plant).filter(Plant.slug == "surya-a").first()
    if not plant:
        plant = db.query(Plant).first()

    if plant:
        user = db.query(User).filter(User.org_id == plant.org_id).first()
        org_id = plant.org_id
        plant_id = plant.id
        user_id = user.id if user else uuid4()
    else:
        # Fallback synthetic IDs if empty database
        org_id = uuid4()
        plant_id = UUID("63d2b0a1-ed00-44d4-97be-0afe76b6749f")
        user_id = uuid4()

    return ToolSecurityContext(
        org_id=org_id,
        user_id=user_id,
        plant_id=plant_id,
        user_role="engineer",
    )


@app.command()
def run(
    threshold: float = typer.Option(
        80.0,
        "--threshold",
        "-t",
        help="Minimum numeric-exact accuracy pass rate required by the CI quality gate (e.g. 80.0 = 80%).",
    ),
    dataset_path: Path = typer.Option(
        _backend_dir / "tests" / "copilot" / "golden_dataset.json",
        "--dataset-path",
        "-d",
        help="Path to load or save the 100 golden test cases.",
    ),
    report_path: Path = typer.Option(
        _backend_dir.parent / "docs" / "copilot-eval-report.md",
        "--report-path",
        "-r",
        help="Path where the Markdown executive evaluation report is written.",
    ),
    json_output: Optional[Path] = typer.Option(
        _backend_dir.parent / "docs" / "copilot-eval-summary.json",
        "--json-output",
        "-j",
        help="Optional path to output machine-readable JSON metrics.",
    ),
    provider: str = typer.Option(
        "ci",
        "--provider",
        "-p",
        help="Evaluation provider mode: 'ci' (deterministic high-speed) or 'live' (real LLM API).",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Optional limit on number of test cases to run (for fast sanity checks).",
    ),
) -> None:
    """Execute the PlantIQ Copilot evaluation suite and enforce the quality gate."""
    console.print(
        Panel.fit(
            f"[bold cyan]PlantIQ Copilot Evaluation Harness (§10.5)[/bold cyan]\n"
            f"[dim]Provider: [bold]{provider.upper()}[/bold] | "
            f"Quality Gate Threshold: [bold]{threshold:.1f}%[/bold][/dim]",
            border_style="cyan",
        )
    )

    # 1. Load or Generate Golden Dataset
    if dataset_path.exists():
        console.print(f"[dim]Loading golden dataset from: {dataset_path}...[/dim]")
        cases = load_golden_dataset_from_file(dataset_path)
    else:
        console.print(f"[dim]Generating 100 golden test cases and saving to {dataset_path}...[/dim]")
        cases = generate_golden_dataset()
        save_golden_dataset_to_file(dataset_path, cases)

    if limit is not None and limit > 0:
        cases = cases[:limit]
        console.print(f"[yellow]Limiting execution to first {limit} test cases.[/yellow]")

    console.print(f"[green]✓ Test suite loaded: {len(cases)} test cases ready.[/green]")

    # 2. Initialize Database Session and Security Context
    db = SessionLocal()
    try:
        context = _get_or_create_eval_context(db)
        console.print(f"[dim]Security context: Plant ID = {context.plant_id}, Org ID = {context.org_id}[/dim]")

        # 3. Configure Orchestrator & Provider
        if provider.lower() == "ci":
            cases_map = {c.question: c for c in cases}
            llm_provider = CIEvaluationProvider(golden_cases_by_question=cases_map)
            orchestrator = CopilotOrchestrator(provider=llm_provider)
        else:
            orchestrator = CopilotOrchestrator()

        # 4. Execute Evaluation Suite
        evaluator = CopilotEvaluator(target_threshold=threshold)
        console.print(f"\n[bold]Evaluating {len(cases)} test cases...[/bold]")

        summary: EvaluationSummary = evaluator.evaluate_suite(
            cases=cases,
            orchestrator=orchestrator,
            context=context,
            session=db,
        )

        # 5. Display Executive Metrics Table
        table = Table(title="PlantIQ Copilot Evaluation Metrics Summary", border_style="bright_blue")
        table.add_column("Evaluation Metric", style="bold", justify="left")
        table.add_column("Target Quality Gate", justify="center")
        table.add_column("Actual Score", justify="center")
        table.add_column("Status", justify="center")

        num_pass = summary.numeric_exact_pass_rate >= threshold
        table.add_row(
            "Numeric-Exact Pass Rate",
            f"≥ {threshold:.1f}%",
            f"[bold {('green' if num_pass else 'red')}]{summary.numeric_exact_pass_rate:.1f}%[/]",
            "✅ PASS" if num_pass else "❌ FAIL",
        )
        table.add_row(
            "Tool Selection Accuracy",
            "≥ 85.0%",
            f"{summary.tool_accuracy_rate:.1f}%",
            "✅ PASS" if summary.tool_accuracy_rate >= 85.0 else "⚠️ WARN",
        )
        table.add_row(
            "Citation Compliance Rate",
            "≥ 90.0%",
            f"{summary.citation_compliance_rate:.1f}%",
            "✅ PASS" if summary.citation_compliance_rate >= 90.0 else "⚠️ WARN",
        )
        table.add_row(
            "Overall End-to-End Pass Rate",
            f"≥ {threshold:.1f}%",
            f"{summary.overall_pass_rate:.1f}%",
            "✅ PASS" if summary.overall_pass_rate >= threshold else "❌ FAIL",
        )
        console.print(table)

        # 6. Display Category Breakdown Table
        cat_table = Table(title="Category Accuracy Breakdown", border_style="dim")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Total Cases", justify="right")
        cat_table.add_column("Passed", justify="right")
        cat_table.add_column("Numeric Exact %", justify="right")
        cat_table.add_column("Category Pass %", justify="right")

        for cat, stats in sorted(summary.category_scores.items()):
            cat_table.add_row(
                cat,
                str(stats["total"]),
                str(stats["passed"]),
                f"{stats['numeric_exact_rate']:.1f}%",
                f"{stats['pass_rate']:.1f}%",
            )
        console.print(cat_table)

        # 7. Write Reports
        report_md = evaluator.generate_markdown_report(summary, output_path=report_path)
        console.print(f"\n[green]✓ Markdown report written to: {report_path}[/green]")

        if json_output:
            json_output.parent.mkdir(parents=True, exist_ok=True)
            with open(json_output, "w", encoding="utf-8") as f:
                json.dump(summary.to_dict(), f, indent=2)
            console.print(f"[green]✓ JSON summary written to: {json_output}[/green]")

        # 8. Enforce CI Quality Gate
        if summary.threshold_met:
            console.print(
                Panel.fit(
                    f"[bold green]QUALITY GATE PASSED: Numeric Accuracy ({summary.numeric_exact_pass_rate:.1f}%) "
                    f"meets or exceeds the {threshold:.1f}% target threshold.[/bold green]",
                    border_style="green",
                )
            )
            sys.exit(0)
        else:
            console.print(
                Panel.fit(
                    f"[bold red]QUALITY GATE FAILED: Numeric Accuracy ({summary.numeric_exact_pass_rate:.1f}%) "
                    f"dropped below the required {threshold:.1f}% threshold.[/bold red]",
                    border_style="red",
                )
            )
            sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    app()
