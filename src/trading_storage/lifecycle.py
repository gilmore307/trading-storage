"""Local storage lifecycle planning and cleanup helpers.

The helpers in this module are deliberately conservative:

- source-controlled files are never candidates;
- durable local artifacts under ``storage/artifacts`` are reported, not deleted;
- logs and development outputs are archived before active copies are removed;
- legacy component-local roots and storage-owned roots are both covered during migration;
- temporary/cache files are deleted only after a short TTL;
- every mutation is opt-in by calling ``apply_retention_plan``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

LifecycleAction = Literal["delete", "archive_then_delete", "retain"]
PlannedAction = Literal["delete", "archive", "retain", "skip"]

DEFAULT_ARCHIVE_ROOT = Path("storage/archive")
PYTHON_CACHE_NAMES = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


@dataclass(frozen=True)
class RetentionRule:
    """Retention behavior for one local ignored storage area."""

    name: str
    roots: tuple[str, ...]
    action: LifecycleAction
    ttl_days: int | None
    description: str


@dataclass(frozen=True)
class LifecyclePlanItem:
    """One file-level lifecycle decision."""

    rule: str
    action: PlannedAction
    path: str
    age_days: float
    byte_count: int
    reason: str
    archive_path: str | None = None
    content_hash_sha256: str | None = None


@dataclass(frozen=True)
class LifecyclePlan:
    """A deterministic lifecycle plan for local storage maintenance."""

    root: str
    generated_at: str
    dry_run: bool
    items: tuple[LifecyclePlanItem, ...]

    @property
    def summary(self) -> dict[str, int]:
        counts = {"archive": 0, "delete": 0, "retain": 0, "skip": 0}
        for item in self.items:
            counts[item.action] += 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "generated_at": self.generated_at,
            "dry_run": self.dry_run,
            "summary": self.summary,
            "items": [asdict(item) for item in self.items],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


DEFAULT_RETENTION_RULES: tuple[RetentionRule, ...] = (
    RetentionRule(
        name="temporary_files",
        roots=("tmp", "storage/tmp", "storage/cache"),
        action="delete",
        ttl_days=3,
        description="Scratch/cache files are disposable after three days and are not archived.",
    ),
    RetentionRule(
        name="diagnostic_logs",
        roots=("logs", "storage/logs"),
        action="archive_then_delete",
        ttl_days=14,
        description="Local logs are archived before active copies older than fourteen days are removed.",
    ),
    RetentionRule(
        name="development_runs",
        roots=("runs", "storage/runs"),
        action="archive_then_delete",
        ttl_days=30,
        description="Local run staging is archived before active copies older than thirty days are removed.",
    ),
    RetentionRule(
        name="development_outputs",
        roots=("outputs", "storage/outputs", "storage/staging"),
        action="archive_then_delete",
        ttl_days=30,
        description="Disposable development outputs are archived before active copies older than thirty days are removed.",
    ),
    RetentionRule(
        name="local_artifacts",
        roots=("storage/artifacts",),
        action="retain",
        ttl_days=None,
        description="Storage-owned local artifacts are retained until a reviewed promotion or deletion policy supersedes them.",
    ),
    RetentionRule(
        name="local_archives",
        roots=("storage/archive",),
        action="delete",
        ttl_days=180,
        description="Local archives are pruned after one hundred eighty days.",
    ),
)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _age_days(path: Path, *, now_ts: float) -> float:
    return max(0.0, (now_ts - path.stat().st_mtime) / 86400.0)


def _iter_files(root: Path, relative_roots: Iterable[str]) -> Iterable[Path]:
    for relative in relative_roots:
        base = root / relative
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() or path.is_symlink():
                yield path


def _iter_python_cache_files(root: Path) -> Iterable[Path]:
    for directory in sorted(root.rglob("*")):
        if ".git" in directory.parts:
            continue
        if not directory.is_dir() or directory.name not in PYTHON_CACHE_NAMES:
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() or path.is_symlink():
                yield path


def _archive_path(root: Path, archive_root: Path, path: Path) -> Path:
    relative = path.relative_to(root)
    if len(relative.parts) >= 2 and relative.parts[0] == "storage" and relative.parts[1] in {"logs", "runs", "outputs", "staging"}:
        relative = Path(*relative.parts[1:])
    candidate = archive_root / relative
    if not candidate.exists():
        return candidate
    existing_hash = sha256_file(candidate)
    current_hash = sha256_file(path)
    if existing_hash == current_hash:
        return candidate
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    return candidate.with_name(f"{stem}.{current_hash.removeprefix('sha256:')[:12]}{suffix}")


def plan_retention(
    root: Path = Path("."),
    *,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    rules: tuple[RetentionRule, ...] = DEFAULT_RETENTION_RULES,
    dry_run: bool = True,
    generated_at: str | None = None,
) -> LifecyclePlan:
    """Plan local storage lifecycle actions without mutating files."""

    root = root.resolve()
    archive_root = archive_root.resolve() if archive_root.is_absolute() else (root / archive_root).resolve()
    try:
        archive_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("archive_root must live under root") from exc
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    items: list[LifecyclePlanItem] = []

    for rule in rules:
        for path in _iter_files(root, rule.roots):
            display_path = str(path.relative_to(root))
            try:
                if path.is_symlink():
                    items.append(
                        LifecyclePlanItem(
                            rule=rule.name,
                            action="skip",
                            path=display_path,
                            age_days=0.0,
                            byte_count=0,
                            reason="symlink skipped",
                        )
                    )
                    continue
                stat = path.stat()
                age = _age_days(path, now_ts=now_ts)
                file_hash = sha256_file(path)
            except OSError as exc:
                items.append(
                    LifecyclePlanItem(
                        rule=rule.name,
                        action="skip",
                        path=display_path,
                        age_days=0.0,
                        byte_count=0,
                        reason=f"stat/hash failed: {exc}",
                    )
                )
                continue

            if rule.action == "retain":
                items.append(
                    LifecyclePlanItem(
                        rule=rule.name,
                        action="retain",
                        path=display_path,
                        age_days=round(age, 3),
                        byte_count=stat.st_size,
                        reason=rule.description,
                        content_hash_sha256=file_hash,
                    )
                )
                continue

            if rule.ttl_days is None or age < rule.ttl_days:
                continue

            if rule.action == "delete":
                items.append(
                    LifecyclePlanItem(
                        rule=rule.name,
                        action="delete",
                        path=display_path,
                        age_days=round(age, 3),
                        byte_count=stat.st_size,
                        reason=f"older than {rule.ttl_days} days; {rule.description}",
                        content_hash_sha256=file_hash,
                    )
                )
            elif rule.action == "archive_then_delete":
                target = _archive_path(root, archive_root, path)
                items.append(
                    LifecyclePlanItem(
                        rule=rule.name,
                        action="archive",
                        path=display_path,
                        age_days=round(age, 3),
                        byte_count=stat.st_size,
                        reason=f"older than {rule.ttl_days} days; archive then remove active copy",
                        archive_path=str(target.relative_to(root)),
                        content_hash_sha256=file_hash,
                    )
                )

    for path in _iter_python_cache_files(root):
        display_path = str(path.relative_to(root))
        try:
            if path.is_symlink():
                items.append(
                    LifecyclePlanItem(
                        rule="python_caches",
                        action="skip",
                        path=display_path,
                        age_days=0.0,
                        byte_count=0,
                        reason="symlink skipped",
                    )
                )
                continue
            stat = path.stat()
            age = _age_days(path, now_ts=now_ts)
            file_hash = sha256_file(path)
        except OSError as exc:
            items.append(
                LifecyclePlanItem(
                    rule="python_caches",
                    action="skip",
                    path=display_path,
                    age_days=0.0,
                    byte_count=0,
                    reason=f"stat/hash failed: {exc}",
                )
            )
            continue
        items.append(
            LifecyclePlanItem(
                rule="python_caches",
                action="delete",
                path=display_path,
                age_days=round(age, 3),
                byte_count=stat.st_size,
                reason="Python/tool cache; disposable and regenerated by tooling",
                content_hash_sha256=file_hash,
            )
        )

    return LifecyclePlan(root=str(root), generated_at=generated_at or now_utc(), dry_run=dry_run, items=tuple(items))


def apply_retention_plan(plan: LifecyclePlan) -> LifecyclePlan:
    """Apply archive/delete actions from a plan and return an executed plan."""

    root = Path(plan.root)
    for item in plan.items:
        path = root / item.path
        if item.action == "delete":
            if path.exists() and not path.is_symlink():
                path.unlink()
        elif item.action == "archive":
            if not item.archive_path:
                continue
            target = root / item.archive_path
            if path.exists() and not path.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(path, target)
                path.unlink()
    _remove_empty_local_dirs(root)
    return LifecyclePlan(root=plan.root, generated_at=now_utc(), dry_run=False, items=plan.items)


def _remove_empty_local_dirs(root: Path) -> None:
    for relative in (
        "tmp",
        "logs",
        "runs",
        "outputs",
        "storage/tmp",
        "storage/cache",
        "storage/logs",
        "storage/runs",
        "storage/outputs",
        "storage/staging",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    ):
        base = root / relative
        if not base.exists() or not base.is_dir():
            continue
        for path in sorted(base.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        try:
            base.rmdir()
        except OSError:
            pass
    for base in sorted(root.rglob("__pycache__"), key=lambda item: len(item.parts), reverse=True):
        try:
            base.rmdir()
        except OSError:
            pass
