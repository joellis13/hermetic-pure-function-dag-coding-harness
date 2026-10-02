"""CLI application for the Hermetic Coding Harness."""
from __future__ import annotations

import asyncio
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hermetic.client.github import GitHubClient, GitHubClientError
from hermetic.compute.critic import CriticNode
from hermetic.compute.driver import AntigravityDriver
from hermetic.compute.implementation_node import ImplementationNode
from hermetic.compute.planning_node import PlanningNode
from hermetic.control.executor import ExecutionResult, TaskExecutionError, execute_plan
from hermetic.control.state_machine import StateMachine
from hermetic.data.etl.assembler import ContextAssembler
from hermetic.data.renderer import render_plan_html, render_report_html, write_html
from hermetic.schemas.context import CodeSnippet, IssueContext
from hermetic.schemas.deliverable import FullImplementationReport
from hermetic.schemas.plan import ImplementationPlan, PlanIterationContext
from hermetic.schemas.run import RunStatus

app = typer.Typer(name="hermetic", help="Hermetic Pure-Function DAG AI Coding Harness")
console = Console()


def _render_plan_table(plan: ImplementationPlan, version: int | None = None) -> Table:
    title = f"Plan {plan.plan_id}" + (f" (Version {version})" if version else "")
    table = Table(title=title)
    table.add_column("Batch", style="cyan")
    table.add_column("Task ID", style="magenta")
    table.add_column("Description", style="white")
    for batch in plan.batches:
        batch_label = batch.description or batch.batch_id
        for task in batch.tasks:
            table.add_row(batch_label, task.id, task.description)
    return table


async def _run_plan(
    issue_number: int,
    repo: Path,
    branch: str,
    model: str,
    owner: str,
    github_repo: str,
    token: str,
    db_path: Path,
    output_dir_override: Path | None,
    files: str | None,
    no_critic: bool,
) -> None:
    repo_resolved = repo.resolve()
    git_dir = repo_resolved / ".git"
    if not git_dir.exists():
        console.print(
            f"[red]Error: Repository directory '{repo}' does not contain a .git directory.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        gh_client = GitHubClient(token)
        # fetch_issue uses urllib (synchronous blocking I/O); offload it to a
        # thread so the asyncio event loop is not stalled during the HTTP round trip.
        issue = await asyncio.to_thread(gh_client.fetch_issue, owner, github_repo, issue_number)
    except GitHubClientError as exc:
        console.print(f"[red]GitHub error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    snippets: list[CodeSnippet] = []
    if files:
        file_list = [f.strip() for f in files.split(",") if f.strip()]
        assembler = ContextAssembler(repo_root=repo_resolved)
        for f_path in file_list:
            if Path(f_path).is_absolute() or f_path.startswith("/") or f_path.startswith("\\"):
                raise typer.BadParameter(
                    f"Absolute paths are not allowed: '{f_path}'. Must be relative to repo root.",
                    param_hint="--files",
                )
            try:
                snippet = assembler.read_file_snippet(f_path)
                snippets.append(snippet)
            except FileNotFoundError as exc:
                raise typer.BadParameter(str(exc), param_hint="--files") from exc

    context = IssueContext(
        issue_id=f"GH-{issue.number}",
        title=issue.title,
        description=issue.body,
        snippets=snippets,
    )

    sm = StateMachine(db_path)
    run_id = await sm.create_run(
        issue_id=context.issue_id,
        repo_path=str(repo_resolved),
        base_branch=branch,
        context=context,
    )

    planner = PlanningNode(AntigravityDriver(model))
    try:
        plan, _ = await planner.plan(context)
    except Exception as exc:
        console.print(f"[red]Planning error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    critic_summary = "Skipped"
    if not no_critic:
        try:
            critic = CriticNode(
                planner_model=model,
                driver_factory=lambda m: AntigravityDriver(m),
            )
            critic_feedback, _ = await critic.evaluate(plan, context)
            verdict = "[green]APPROVED[/green]" if critic_feedback.approved else "[yellow]REJECTED[/yellow]"
            critic_summary = f"{verdict} — {critic_feedback.comments}"
            console.print(Panel(critic_summary, title="Critic Evaluation", expand=False))
        except Exception as exc:
            critic_summary = f"[red]Critic error: {exc}[/red]"
            console.print(f"[yellow]Warning: Critic failed ({exc}). Continuing with plan.[/yellow]")

    version = await sm.save_plan(run_id, plan, feedback="")

    out_dir = output_dir_override or (repo_resolved / ".harness" / "runs" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "plan.html"
    html = render_plan_html(plan, context=context)
    write_html(html, html_path)

    total_tasks = sum(len(b.tasks) for b in plan.batches)
    summary = (
        f"[bold]Run ID:[/bold] {run_id}\n"
        f"[bold]Version:[/bold] {version}\n"
        f"[bold]Batches:[/bold] {len(plan.batches)}\n"
        f"[bold]Tasks:[/bold] {total_tasks}\n"
        f"[bold]Critic:[/bold] {critic_summary}\n"
        f"[bold]HTML:[/bold] {html_path}"
    )
    console.print(Panel(summary, title="[green]Plan Generated[/green]", expand=False))
    console.print("\nNext steps:")
    console.print(f"  Review plan:  [bold]hermetic review {run_id}[/bold]")
    console.print(f"  Approve plan: [bold]hermetic approve {run_id}[/bold]")


@app.command(name="plan")
def plan_command(
    issue_number: int = typer.Argument(..., help="GitHub issue number"),
    repo: Path = typer.Option(Path("."), help="Target git repository root"),
    branch: str = typer.Option("main", help="Base branch"),
    model: str = typer.Option("claude-sonnet-4-6", help="Planner model"),
    owner: str | None = typer.Option(None, envvar="GITHUB_OWNER", help="GitHub org/user"),
    github_repo: str | None = typer.Option(None, envvar="GITHUB_REPO", help="GitHub repo name"),
    token: str | None = typer.Option(None, envvar="GITHUB_TOKEN", help="GitHub PAT"),
    db: Path | None = typer.Option(None, help="SQLite state DB path"),
    output: Path | None = typer.Option(None, help="plan.html output directory"),
    files: str | None = typer.Option(
        None,
        help="Comma-separated repo-relative file paths to attach as code context",
    ),
    no_critic: bool = typer.Option(False, "--no-critic", help="Skip CriticNode"),
) -> None:
    """Generate an ImplementationPlan for a GitHub issue."""
    if not token:
        console.print(
            "[red]Error: GITHUB_TOKEN is required. Provide --token or set GITHUB_TOKEN environment variable.[/red]"
        )
        raise typer.Exit(code=1)

    if not owner or not github_repo:
        console.print(
            "[red]Error: Both --owner and --github-repo are required (or set GITHUB_OWNER / GITHUB_REPO).[/red]"
        )
        raise typer.Exit(code=1)

    db_path = db or (repo.resolve() / ".harness" / "state.db")

    asyncio.run(
        _run_plan(
            issue_number=issue_number,
            repo=repo,
            branch=branch,
            model=model,
            owner=owner,
            github_repo=github_repo,
            token=token,
            db_path=db_path,
            output_dir_override=output,
            files=files,
            no_critic=no_critic,
        )
    )


async def _run_review(
    run_id: str,
    repo: Path,
    model: str,
    db_path: Path,
    no_critic: bool,
) -> None:
    sm = StateMachine(db_path)
    run = await sm.get_run(run_id)
    if run is None:
        console.print(f"[red]Error: Run {run_id} not found.[/red]")
        raise typer.Exit(code=1)

    latest = await sm.get_latest_plan(run_id)
    if latest is None:
        console.print(f"[red]Error: No plan checkpoints found for run {run_id}.[/red]")
        raise typer.Exit(code=1)

    current_plan, current_version = latest
    console.print(_render_plan_table(current_plan, current_version))

    feedback = typer.prompt("Enter feedback (empty to exit without changes)", default="")
    if not feedback.strip():
        console.print("No feedback provided. Exiting.")
        raise typer.Exit(code=0)

    context = await sm.get_context(run_id)
    if context is None:
        console.print(f"[red]Error: Context snapshot missing for run {run_id}.[/red]")
        raise typer.Exit(code=1)

    iteration_ctx = PlanIterationContext(
        iteration=current_version,
        feedback=feedback.strip(),
    )
    planner = PlanningNode(AntigravityDriver(model))
    try:
        revised_plan, _ = await planner.plan(context, iteration=iteration_ctx)
    except Exception as exc:
        console.print(f"[red]Planning error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    critic_summary = "Skipped"
    if not no_critic:
        try:
            critic = CriticNode(
                planner_model=model,
                driver_factory=lambda m: AntigravityDriver(m),
            )
            crit_feedback, _ = await critic.evaluate(revised_plan, context)
            verdict = "[green]APPROVED[/green]" if crit_feedback.approved else "[yellow]REJECTED[/yellow]"
            critic_summary = f"{verdict} — {crit_feedback.comments}"
            console.print(Panel(critic_summary, title="Critic Evaluation", expand=False))
            if not crit_feedback.approved:
                proceed = typer.confirm("Proceed anyway?", default=False)
                if not proceed:
                    console.print("[yellow]Revised plan discarded due to critic feedback.[/yellow]")
                    raise typer.Exit(code=0)
        except typer.Exit:
            raise
        except Exception as exc:
            critic_summary = f"[red]Critic error: {exc}[/red]"
            console.print(f"[yellow]Warning: Critic failed ({exc}). Proceeding.[/yellow]")

    new_version = await sm.save_plan(run_id, revised_plan, feedback=feedback.strip())

    out_dir = Path(run.repo_path) / ".harness" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "plan.html"
    html = render_plan_html(revised_plan, context=context)
    write_html(html, html_path)

    summary = (
        f"[bold]Run ID:[/bold] {run_id}\n"
        f"[bold]New Version:[/bold] {new_version}\n"
        f"[bold]Critic:[/bold] {critic_summary}\n"
        f"[bold]HTML:[/bold] {html_path}"
    )
    console.print(Panel(summary, title="[green]Plan Revised[/green]", expand=False))


@app.command(name="review")
def review_command(
    run_id: str = typer.Argument(..., help="Run ID (UUID)"),
    repo: Path = typer.Option(Path("."), help="Target git repository root"),
    model: str = typer.Option("claude-sonnet-4-6", help="Planner model"),
    db: Path | None = typer.Option(None, help="SQLite state DB path"),
    no_critic: bool = typer.Option(False, "--no-critic", help="Skip CriticNode"),
) -> None:
    """Review and revise an existing plan with interactive feedback."""
    db_path = db or (repo.resolve() / ".harness" / "state.db")
    asyncio.run(
        _run_review(
            run_id=run_id,
            repo=repo,
            model=model,
            db_path=db_path,
            no_critic=no_critic,
        )
    )


async def _run_approve(
    run_id: str,
    db_path: Path,
    version: int | None,
) -> None:
    sm = StateMachine(db_path)
    run = await sm.get_run(run_id)
    if run is None:
        console.print(f"[red]Error: Run {run_id} not found.[/red]")
        raise typer.Exit(code=1)

    if run.status != RunStatus.PLANNING.value:
        console.print(
            f"[red]Error: Cannot approve run in status '{run.status}'. Must be in 'planning'.[/red]"
        )
        raise typer.Exit(code=1)

    if version is not None:
        plan = await sm.get_plan_version(run_id, version)
        if plan is None:
            console.print(f"[red]Error: Plan version {version} not found for run {run_id}.[/red]")
            raise typer.Exit(code=1)
        target_version = version
    else:
        latest = await sm.get_latest_plan(run_id)
        if latest is None:
            console.print(f"[red]Error: No plan checkpoints found for run {run_id}.[/red]")
            raise typer.Exit(code=1)
        plan, target_version = latest

    console.print(_render_plan_table(plan, target_version))

    approved = typer.confirm("Approve this plan?", default=False)
    if not approved:
        console.print("[yellow]Plan approval aborted.[/yellow]")
        raise typer.Exit(code=0)

    await sm.update_run_status(run_id, RunStatus.APPROVED)
    console.print(f"[bold green]Run {run_id} approved (plan v{target_version})![/bold green]")
    console.print(f"To execute: [bold]hermetic implement {run_id}[/bold]")


@app.command(name="approve")
def approve_command(
    run_id: str = typer.Argument(..., help="Run ID (UUID)"),
    repo: Path = typer.Option(Path("."), help="Target git repository root"),
    db: Path | None = typer.Option(None, help="SQLite state DB path"),
    version: int | None = typer.Option(None, help="Specific plan version to approve (default: latest)"),
) -> None:
    """Approve a plan for implementation."""
    db_path = db or (repo.resolve() / ".harness" / "state.db")
    asyncio.run(
        _run_approve(
            run_id=run_id,
            db_path=db_path,
            version=version,
        )
    )


async def _run_implement(
    run_id: str,
    repo: Path,
    model: str,
    db_path: Path,
    max_retries: int,
    dry_run: bool,
) -> None:
    repo_resolved = repo.resolve()
    sm = StateMachine(db_path)
    run = await sm.get_run(run_id)
    if run is None:
        console.print(f"[red]Error: Run {run_id} not found.[/red]")
        raise typer.Exit(code=1)

    if run.status != RunStatus.APPROVED.value:
        console.print(
            f"[red]Error: Cannot execute run in status '{run.status}'. "
            f"Run must be in 'approved' status (use 'hermetic approve {run_id}' first).[/red]"
        )
        raise typer.Exit(code=1)

    latest = await sm.get_latest_plan(run_id)
    if latest is None:
        console.print(f"[red]Error: No plan checkpoints found for run {run_id}.[/red]")
        raise typer.Exit(code=1)
    plan, plan_version = latest

    if dry_run:
        console.print(
            Panel(
                f"[bold]Run ID:[/bold] {run_id}\n"
                f"[bold]Plan Version:[/bold] {plan_version}\n"
                f"[bold]Batches:[/bold] {len(plan.batches)}\n"
                f"[bold]Tasks:[/bold] {sum(len(b.tasks) for b in plan.batches)}\n"
                "[yellow]Dry run mode: skipped worktree writes and execution.[/yellow]",
                title="[cyan]Dry Run Complete[/cyan]",
                expand=False,
            )
        )
        return

    await sm.update_run_status(run_id, RunStatus.EXECUTING)
    console.print(
        Panel(
            f"[bold]Run ID:[/bold] {run_id}\n"
            f"[bold]Plan Version:[/bold] {plan_version}\n"
            f"[bold]Model:[/bold] {model}\n"
            f"[bold]Max Retries:[/bold] {max_retries}\n"
            f"[bold]Dry Run:[/bold] {dry_run}",
            title="[cyan]Starting Execution[/cyan]",
            expand=False,
        )
    )

    impl_node = ImplementationNode(AntigravityDriver(model))
    repo_path = Path(run.repo_path)
    base_branch = run.base_branch

    try:
        result: ExecutionResult = await execute_plan(
            plan,
            repo_path,
            base_branch,
            impl_node,
            max_retries=max_retries,
        )
    except TaskExecutionError as exc:
        await sm.update_run_status(run_id, RunStatus.FAILED)
        console.print(
            Panel(
                f"[red]Task '{exc.task_id}' failed after all retries.[/red]\n{exc.message}",
                title="[red]Execution Failed[/red]",
                expand=False,
            )
        )
        # Save partial report
        partial_report = FullImplementationReport(
            plan_id=plan.plan_id,
            deliverables=[],
            failed_tasks=[exc.task_id],
            summary=f"Run failed: task '{exc.task_id}' exhausted all retries.",
        )
        await sm.save_report(run_id, partial_report)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        await sm.update_run_status(run_id, RunStatus.FAILED)
        console.print(f"[red]Unexpected error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    # Save deliverables
    for deliverable in result.deliverables:
        batch_idx = next(
            (bi for bi, b in enumerate(plan.batches) if any(t.id == deliverable.task_id for t in b.tasks)),
            0,
        )
        await sm.save_deliverable(run_id, batch_index=batch_idx, deliverable=deliverable)

    # Build and save the full report
    total_tasks = sum(len(b.tasks) for b in plan.batches)
    report = FullImplementationReport(
        plan_id=plan.plan_id,
        deliverables=result.deliverables,
        failed_tasks=[],  # execute_plan only returns on full success; failures raise TaskExecutionError
        total_input_tokens=result.total_input_tokens,
        total_output_tokens=result.total_output_tokens,
        summary=(
            f"Executed {len(result.deliverables)}/{total_tasks} tasks successfully "
            f"across {len(plan.batches)} batch(es)."
        ),
    )
    await sm.update_run_status(run_id, RunStatus.DONE)
    await sm.save_report(run_id, report)

    # Render and write full_report.html
    out_dir = repo_resolved / ".harness" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "full_report.html"
    html = render_report_html(report)
    write_html(html, html_path)

    console.print(
        Panel(
            f"[bold]Run ID:[/bold] {run_id}\n"
            f"[bold]Status:[/bold] [green]DONE[/green]\n"
            f"[bold]Deliverables:[/bold] {len(result.deliverables)}/{total_tasks}\n"
            f"[bold]Input Tokens:[/bold] {result.total_input_tokens:,}\n"
            f"[bold]Output Tokens:[/bold] {result.total_output_tokens:,}\n"
            f"[bold]Report:[/bold] {html_path}",
            title="[green]Execution Complete[/green]",
            expand=False,
        )
    )


@app.command(name="implement")
def implement_command(
    run_id: str = typer.Argument(..., help="Run ID (UUID)"),
    repo: Path = typer.Option(Path("."), help="Target git repository root"),
    model: str = typer.Option("gemini-flash", help="Implementation model (fast model recommended)"),
    db: Path | None = typer.Option(None, help="SQLite state DB path"),
    max_retries: int = typer.Option(3, help="Max retries per task (0-3)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse plan + validate but skip worktree writes"),
) -> None:
    """Execute an approved ImplementationPlan across ephemeral git worktrees."""
    db_path = db or (repo.resolve() / ".harness" / "state.db")
    asyncio.run(
        _run_implement(
            run_id=run_id,
            repo=repo,
            model=model,
            db_path=db_path,
            max_retries=max_retries,
            dry_run=dry_run,
        )
    )

