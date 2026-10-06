#!/usr/bin/env python3
"""Historical KPI Backfill CLI Tool (§11, Task S3-AI-01).

Implements:
- Manual triggering of historical solar KPI rollups per plant and per inverter.
- Configurable plant filter (--plant-id, --plant-name, or --all-plants).
- Calendar date range traversal (--start-date to --end-date).
- Execution modes:
    * Synchronous execution (default, interactive with Rich terminal tables).
    * Celery async dispatch (--async-celery) submitting tasks to background workers.
- Dry-run validation mode (--dry-run).
- Formatted summary metrics showing Energy, Yield, PR, CUF, Availability, Coverage, and Flags.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from uuid import UUID

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy import select
import typer

# Ensure both backend/ and repo root are in sys.path
_backend_dir = str(Path(__file__).resolve().parent.parent)
_repo_dir = str(Path(__file__).resolve().parent.parent.parent)
for p in [_backend_dir, _repo_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.core.celery_app import celery_app
from app.db.session import create_db_engine, get_session_factory
from app.models.entities import KPIValue, Plant
from app.tasks.kpi_tasks import compute_daily_kpis, compute_daily_kpis_for_plant

app = typer.Typer(
    name="backfill-kpis",
    help="PlantIQ Solar KPI Historical Backfill CLI Tool",
    add_completion=False,
)
console = Console()


def daterange(start_date: date, end_date: date) -> List[date]:
    """Generate list of inclusive dates between start_date and end_date."""
    dates: List[date] = []
    curr = start_date
    while curr <= end_date:
        dates.append(curr)
        curr += timedelta(days=1)
    return dates


@app.command()
def main(
    start_date: str = typer.Option(
        ...,
        "--start-date",
        "-s",
        help="Start date in YYYY-MM-DD format (inclusive).",
    ),
    end_date: str = typer.Option(
        ...,
        "--end-date",
        "-e",
        help="End date in YYYY-MM-DD format (inclusive).",
    ),
    plant_id: Optional[str] = typer.Option(
        None,
        "--plant-id",
        help="Filter by specific Plant UUID.",
    ),
    plant_name: Optional[str] = typer.Option(
        None,
        "--plant-name",
        help="Filter by specific Plant name (e.g., 'Surya-A').",
    ),
    all_plants: bool = typer.Option(
        False,
        "--all-plants",
        help="Backfill KPIs for all registered plants.",
    ),
    async_celery: bool = typer.Option(
        False,
        "--async-celery",
        help="Dispatch calculations asynchronously via Celery worker queue.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview days and plants without executing or writing to database.",
    ),
    db_url: Optional[str] = typer.Option(
        None,
        "--db-url",
        help="Optional database connection URL override.",
    ),
) -> None:
    """Execute historical KPI rollup backfill across specified date range."""
    # 1. Parse dates
    try:
        s_date = date.fromisoformat(start_date)
        e_date = date.fromisoformat(end_date)
    except ValueError as exc:
        console.print(f"[bold red]Error parsing date:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if s_date > e_date:
        console.print("[bold red]Start date must be earlier than or equal to end date.[/bold red]")
        raise typer.Exit(code=1)

    dates_to_process = daterange(s_date, e_date)

    # 2. Connect to database
    engine = create_db_engine(db_url)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        query = select(Plant)
        if plant_id:
            try:
                p_uuid = UUID(plant_id)
                query = query.where(Plant.id == p_uuid)
            except ValueError:
                console.print(f"[bold red]Invalid Plant UUID:[/bold red] {plant_id}")
                raise typer.Exit(code=1)
        elif plant_name:
            query = query.where(Plant.name.ilike(f"%{plant_name}%"))
        elif not all_plants:
            # Default to first plant found if none specified
            console.print("[yellow]No plant specified; defaulting to all plants (--all-plants).[/yellow]")

        target_plants = session.scalars(query).all()

        if not target_plants:
            console.print("[bold red]No matching plants found in database.[/bold red]")
            raise typer.Exit(code=1)

        # Print header
        plant_names = ", ".join(p.name for p in target_plants)
        console.print(
            Panel(
                f"[bold cyan]PlantIQ Historical KPI Backfill[/bold cyan]\n"
                f"Plants: [green]{plant_names}[/green] ({len(target_plants)} plant(s))\n"
                f"Date Range: [yellow]{s_date.isoformat()} to {e_date.isoformat()}[/yellow] "
                f"({len(dates_to_process)} day(s))\n"
                f"Mode: [magenta]{'Celery Asynchronous' if async_celery else 'Synchronous'}[/magenta] "
                f"{'(DRY-RUN)' if dry_run else ''}",
                title="S3-AI-01 KPI Engine",
                expand=False,
            )
        )

        if dry_run:
            console.print(f"[green]Dry run complete. Would process {len(target_plants) * len(dates_to_process)} plant-day rollups.[/green]")
            return

        table = Table(
            title="KPI Backfill Execution Summary",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Date", style="dim", width=12)
        table.add_column("Plant", style="bold green", width=14)
        table.add_column("Inverters", justify="right", width=10)
        table.add_column("Energy AC (kWh)", justify="right", width=16)
        table.add_column("Spec Yield (kWh/kWp)", justify="right", width=20)
        table.add_column("PR (%)", justify="right", width=10)
        table.add_column("CUF (%)", justify="right", width=10)
        table.add_column("Availability (%)", justify="right", width=16)
        table.add_column("Coverage", justify="right", width=10)
        table.add_column("Status", width=10)

        total_persisted = 0
        total_days_processed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Processing KPI rollups...",
                total=len(target_plants) * len(dates_to_process),
            )

            for target_plant in target_plants:
                for d in dates_to_process:
                    if async_celery:
                        # Submit task asynchronously to Celery
                        compute_daily_kpis.delay(
                            str(target_plant.id),
                            d.isoformat(),
                        )
                        table.add_row(
                            d.isoformat(),
                            target_plant.name,
                            "-",
                            "-",
                            "-",
                            "-",
                            "-",
                            "-",
                            "-",
                            "[cyan]QUEUED[/cyan]",
                        )
                    else:
                        # Execute synchronously
                        summary = compute_daily_kpis_for_plant(
                            session=session,
                            plant=target_plant,
                            target_date=d,
                        )
                        p_kpis = summary.get("plant_kpis", {})
                        e_ac = p_kpis.get("energy_ac", {}).get("value")
                        s_yield = p_kpis.get("specific_yield", {}).get("value")
                        pr = p_kpis.get("pr", {}).get("value")
                        cuf = p_kpis.get("cuf", {}).get("value")
                        avail = p_kpis.get("availability", {}).get("value")
                        cov = p_kpis.get("energy_ac", {}).get("coverage", 0.0)

                        e_str = f"{e_ac:,.1f}" if e_ac is not None else "[dim]N/A[/dim]"
                        y_str = f"{s_yield:.2f}" if s_yield is not None else "[dim]N/A[/dim]"
                        pr_str = f"{pr * 100:.1f}%" if pr is not None else "[dim]N/A[/dim]"
                        cuf_str = f"{cuf * 100:.1f}%" if cuf is not None else "[dim]N/A[/dim]"
                        avail_str = f"{avail * 100:.1f}%" if avail is not None else "[dim]N/A[/dim]"
                        cov_str = f"{cov * 100:.0f}%"

                        table.add_row(
                            d.isoformat(),
                            target_plant.name,
                            str(summary.get("inverters_count", 0)),
                            e_str,
                            y_str,
                            pr_str,
                            cuf_str,
                            avail_str,
                            cov_str,
                            "[green]SUCCESS[/green]",
                        )
                        total_persisted += summary.get("persisted_records", 0)

                    total_days_processed += 1
                    progress.advance(task)

        console.print(table)
        console.print(
            f"[bold green]Backfill completed successfully![/bold green] "
            f"Processed {total_days_processed} plant-day rollups, persisted {total_persisted} KPI records."
        )


if __name__ == "__main__":
    app()
