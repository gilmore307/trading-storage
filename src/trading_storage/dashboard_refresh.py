"""Dashboard read-model refresh orchestration.

This module owns storage-side refresh orchestration for dashboard read models:
it runs an upstream semantic producer, validates the returned dashboard envelope,
and materializes the storage-owned snapshot/latest/schema/index layout.  It does
not interpret manager internals, call providers, activate models, submit broker
orders, or mutate account state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_store import now_utc
from .dashboard_read_models import MaterializedDashboardReadModel, materialize_dashboard_read_model

HISTORICAL_TASK_PROGRESS_CONTRACT = "historical_task_progress_summary"
REFRESH_RECEIPT_CONTRACT = "dashboard_read_model_refresh_receipt"
DEFAULT_TRADING_MANAGER_ROOT = Path(os.environ.get("TRADING_MANAGER_ROOT", "/root/projects/trading-manager"))
DEFAULT_PRODUCER_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class DashboardReadModelRefreshResult:
    """Result metadata for one dashboard read-model refresh."""

    refreshed_contract_type: str
    producer_argv: tuple[str, ...]
    producer_cwd: Path | None
    producer_stdout_byte_count: int
    materialized: MaterializedDashboardReadModel
    receipt: dict[str, Any]


def _producer_environment(*, producer_pythonpath: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    if producer_pythonpath is None:
        return env
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(producer_pythonpath) if not current else f"{producer_pythonpath}{os.pathsep}{current}"
    return env


def latest_stage_coverage_path(*, trading_manager_root: Path = DEFAULT_TRADING_MANAGER_ROOT) -> Path | None:
    """Return the newest manager stage-coverage artifact, if one exists."""

    coverage_root = Path(trading_manager_root) / "storage" / "runtime" / "stage_coverage"
    try:
        matches = [path for path in coverage_root.glob("*.json") if path.is_file()]
    except OSError:
        return None
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def build_historical_task_progress_producer_argv(
    *,
    trading_manager_root: Path = DEFAULT_TRADING_MANAGER_ROOT,
    stage_coverage_path: Path | None = None,
) -> tuple[str, ...]:
    """Build argv for the manager-owned historical progress semantic producer."""

    trading_manager_root = Path(trading_manager_root)
    argv: list[str] = [
        sys.executable,
        str(trading_manager_root / "scripts" / "tasks" / "build_historical_task_progress_summary.py"),
    ]
    if stage_coverage_path is not None:
        argv.extend(["--stage-coverage-path", str(stage_coverage_path)])
    return tuple(argv)


def run_dashboard_read_model_producer(
    producer_argv: Sequence[str],
    *,
    producer_cwd: Path | None = None,
    producer_pythonpath: Path | None = None,
    timeout_seconds: float = DEFAULT_PRODUCER_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], int]:
    """Run a semantic producer command and parse its JSON object stdout."""

    completed = subprocess.run(
        tuple(producer_argv),
        cwd=producer_cwd,
        env=_producer_environment(producer_pythonpath=producer_pythonpath),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"dashboard read-model producer failed with exit code {completed.returncode}: {stderr}")
    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError("dashboard read-model producer emitted empty stdout")
    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("dashboard read-model producer must emit one JSON object")
    return payload, len(completed.stdout.encode("utf-8"))


def refresh_dashboard_read_model_from_producer(
    *,
    producer_argv: Sequence[str],
    storage_root: Path,
    expected_contract_type: str,
    producer_cwd: Path | None = None,
    producer_pythonpath: Path | None = None,
    timeout_seconds: float = DEFAULT_PRODUCER_TIMEOUT_SECONDS,
) -> DashboardReadModelRefreshResult:
    """Run a semantic producer and materialize its dashboard read-model payload."""

    payload, stdout_byte_count = run_dashboard_read_model_producer(
        producer_argv,
        producer_cwd=producer_cwd,
        producer_pythonpath=producer_pythonpath,
        timeout_seconds=timeout_seconds,
    )
    materialized = materialize_dashboard_read_model(
        payload,
        storage_root=storage_root,
        expected_contract_type=expected_contract_type,
    )
    receipt = {
        "contract_type": REFRESH_RECEIPT_CONTRACT,
        "generated_at_utc": now_utc(),
        "refreshed_contract_type": expected_contract_type,
        "producer": {
            "argv": list(producer_argv),
            "cwd": str(producer_cwd) if producer_cwd is not None else None,
            "stdout_byte_count": stdout_byte_count,
        },
        "materialized": materialized.index_row,
        "side_effects": {
            "provider_calls": False,
            "model_activation": False,
            "broker_execution": False,
            "account_mutation": False,
            "storage_dashboard_write": True,
        },
    }
    return DashboardReadModelRefreshResult(
        refreshed_contract_type=expected_contract_type,
        producer_argv=tuple(producer_argv),
        producer_cwd=producer_cwd,
        producer_stdout_byte_count=stdout_byte_count,
        materialized=materialized,
        receipt=receipt,
    )


def refresh_historical_task_progress_read_model(
    *,
    trading_manager_root: Path = DEFAULT_TRADING_MANAGER_ROOT,
    storage_root: Path = Path("storage"),
    stage_coverage_path: Path | None = None,
    timeout_seconds: float = DEFAULT_PRODUCER_TIMEOUT_SECONDS,
) -> DashboardReadModelRefreshResult:
    """Refresh the first accepted historical task-progress dashboard read model."""

    trading_manager_root = Path(trading_manager_root)
    stage_coverage_path = stage_coverage_path or latest_stage_coverage_path(trading_manager_root=trading_manager_root)
    producer_argv = build_historical_task_progress_producer_argv(
        trading_manager_root=trading_manager_root,
        stage_coverage_path=stage_coverage_path,
    )
    return refresh_dashboard_read_model_from_producer(
        producer_argv=producer_argv,
        producer_cwd=trading_manager_root,
        producer_pythonpath=trading_manager_root / "src",
        storage_root=storage_root,
        expected_contract_type=HISTORICAL_TASK_PROGRESS_CONTRACT,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "DEFAULT_TRADING_MANAGER_ROOT",
    "HISTORICAL_TASK_PROGRESS_CONTRACT",
    "REFRESH_RECEIPT_CONTRACT",
    "DashboardReadModelRefreshResult",
    "build_historical_task_progress_producer_argv",
    "latest_stage_coverage_path",
    "refresh_dashboard_read_model_from_producer",
    "refresh_historical_task_progress_read_model",
    "run_dashboard_read_model_producer",
]
