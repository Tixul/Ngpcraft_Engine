"""Run the validation suite end-to-end and write a compact QA report."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from core.export_validation import collect_export_pipeline_issues
from core.headless_export import export_project
from core.validation_suite import build_validation_suite


@dataclass
class ValidationCaseResult:
    """Outcome for one generated validation project."""

    project_name: str
    project_dir: str
    export_exit_code: int
    preflight_issue_count: int
    post_issue_count: int
    generated_checks_ok: bool
    generated_checks: list[str]
    build_attempted: bool
    build_exit_code: int | None
    build_ok: bool
    build_summary: str
    build_log_tail: list[str]
    runtime_smoke_requested: bool
    runtime_smoke_attempted: bool
    runtime_smoke_ok: bool
    runtime_smoke_summary: str
    runtime_smoke_artifact: str
    log_lines: list[str]


def _load_project(project_file: Path) -> dict:
    return json.loads(project_file.read_text(encoding="utf-8"))


def _generated_checks(project_dir: Path, project_data: dict) -> tuple[bool, list[str]]:
    export_dir_rel = str(project_data.get("export_dir") or "").strip()
    if not export_dir_rel:
        return False, ["export_dir missing"]
    export_dir = project_dir / export_dir_rel
    checks: list[str] = []
    ok = True

    for required in ("assets_autogen.mk", "scenes_autogen.h", "scenes_autogen.c"):
        path = export_dir / required
        if path.exists():
            checks.append(f"OK {required}")
        else:
            checks.append(f"MISS {required}")
            ok = False

    scenes = [s for s in (project_data.get("scenes") or []) if isinstance(s, dict)]
    for scene in scenes:
        label = str(scene.get("label") or scene.get("id") or "scene").strip()
        safe = "".join(ch.lower() if ch.isalnum() or ch == "_" else "_" for ch in label).strip("_") or "scene"
        if safe and safe[0].isdigit():
            safe = "_" + safe
        for suffix in (f"scene_{safe}.h", f"scene_{safe}_level.h"):
            path = export_dir / suffix
            if path.exists():
                checks.append(f"OK {suffix}")
            else:
                checks.append(f"MISS {suffix}")
                ok = False
    return ok, checks


def _summarize_build_output(stdout: str, stderr: str) -> tuple[str, list[str]]:
    combined = [line.strip() for line in (stdout.splitlines() + stderr.splitlines()) if line.strip()]
    if not combined:
        return "no build output", []
    tail = combined[-12:]
    lower_tail = [line.lower() for line in tail]
    if any("can't execute" in line and "thc1" in line for line in lower_tail):
        return "toolchain incomplete: thc1 missing", tail
    if any("make:" in line and "not found" in line for line in lower_tail):
        return "make not found in PATH", tail
    return tail[-1], tail


def _run_make(project_dir: Path, log: Callable[[str], None]) -> tuple[int | None, bool, str, list[str]]:
    log(f"[QA-1] build {project_dir.name}")
    try:
        proc = subprocess.run(
            ["make"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError:
        return None, False, "make not found in PATH", []
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        summary, tail = _summarize_build_output(stdout, stderr)
        return None, False, f"build timeout ({summary})", tail
    summary, tail = _summarize_build_output(proc.stdout, proc.stderr)
    return int(proc.returncode), proc.returncode == 0, summary, tail


def _detect_rom(project_dir: Path) -> Path | None:
    roots = [project_dir]
    for sub in ("build", "out", "bin", "dist"):
        d = project_dir / sub
        if d.exists():
            roots.insert(0, d)

    best: Path | None = None
    best_mtime = -1.0
    for root in roots:
        for ext in (".ngp", ".ngc"):
            for cand in root.glob(f"*{ext}"):
                try:
                    mtime = cand.stat().st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best_mtime = mtime
                    best = cand
    return best


def _detect_emulator() -> str | None:
    env_emu = os.environ.get("NGPNG_SMOKE_EMULATOR", "").strip()
    if env_emu:
        return env_emu
    for cmd in ("mednafen", "race", "neopop"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _run_runtime_smoke(
    project_dir: Path,
    log: Callable[[str], None],
) -> tuple[bool, bool, str, str]:
    rom = _detect_rom(project_dir)
    if rom is None:
        return False, False, "ROM not found after build", ""
    emu = _detect_emulator()
    if not emu:
        return False, False, "runtime smoke skipped: emulator not found", str(rom)
    log(f"[QA-1] smoke {project_dir.name} -> {Path(emu).name} {rom.name}")
    try:
        proc = subprocess.Popen(
            [emu, str(rom)],
            cwd=str(rom.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return True, False, f"emulator launch failed: {exc}", str(rom)
    time.sleep(2.0)
    exit_code = proc.poll()
    if exit_code is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        return True, True, f"emulator launched: {Path(emu).name}", str(rom)
    if exit_code == 0:
        return True, True, f"emulator exited cleanly: {Path(emu).name}", str(rom)
    return True, False, f"emulator exited with code {exit_code}", str(rom)


def _run_one_project(
    project_file: Path,
    log: Callable[[str], None],
    *,
    build_projects: bool = False,
    smoke_run: bool = False,
) -> ValidationCaseResult:
    log_lines: list[str] = []

    def _capture(msg: str) -> None:
        line = str(msg)
        log_lines.append(line)
        log(line)

    project_data = _load_project(project_file)
    project_dir = project_file.parent
    pre_issues = collect_export_pipeline_issues(project_dir, project_data)
    rc = export_project(project_file, log=_capture)
    refreshed = _load_project(project_file)
    post_issues = collect_export_pipeline_issues(project_dir, refreshed)
    checks_ok, checks = _generated_checks(project_dir, refreshed)
    build_rc: int | None = None
    build_ok = False
    build_summary = "not attempted"
    build_tail: list[str] = []
    smoke_attempted = False
    smoke_ok = False
    smoke_summary = "not requested"
    smoke_artifact = ""
    if build_projects and rc == 0 and checks_ok:
        build_rc, build_ok, build_summary, build_tail = _run_make(project_dir, _capture)
    if smoke_run:
        if build_projects and not build_ok:
            smoke_summary = "not attempted: build failed"
        else:
            smoke_attempted, smoke_ok, smoke_summary, smoke_artifact = _run_runtime_smoke(project_dir, _capture)
    return ValidationCaseResult(
        project_name=str(refreshed.get("name") or project_dir.name),
        project_dir=str(project_dir),
        export_exit_code=int(rc),
        preflight_issue_count=len(pre_issues),
        post_issue_count=len(post_issues),
        generated_checks_ok=bool(checks_ok),
        generated_checks=list(checks),
        build_attempted=bool(build_projects and rc == 0 and checks_ok),
        build_exit_code=build_rc,
        build_ok=bool(build_ok),
        build_summary=str(build_summary),
        build_log_tail=list(build_tail),
        runtime_smoke_requested=bool(smoke_run),
        runtime_smoke_attempted=bool(smoke_attempted),
        runtime_smoke_ok=bool(smoke_ok),
        runtime_smoke_summary=str(smoke_summary),
        runtime_smoke_artifact=str(smoke_artifact),
        log_lines=log_lines,
    )


def _write_reports(destination_root: Path, results: list[ValidationCaseResult]) -> tuple[Path, Path]:
    md_path = destination_root / "VALIDATION_RUN.md"
    json_path = destination_root / "validation_run.json"

    total = len(results)
    ok_count = sum(
        1
        for r in results
        if r.export_exit_code == 0
        and r.generated_checks_ok
        and (not r.build_attempted or r.build_ok)
        and (not r.runtime_smoke_attempted or r.runtime_smoke_ok)
    )
    build_count = sum(1 for r in results if r.build_attempted)
    build_ok_count = sum(1 for r in results if r.build_attempted and r.build_ok)
    smoke_req_count = sum(1 for r in results if r.runtime_smoke_requested)
    smoke_attempted_count = sum(1 for r in results if r.runtime_smoke_attempted)
    smoke_ok_count = sum(1 for r in results if r.runtime_smoke_attempted and r.runtime_smoke_ok)
    md_lines = [
        "# NGPC PNG Manager validation run\n",
        "\n",
        f"- projects: {total}\n",
        f"- fully OK: {ok_count}\n",
        f"- builds attempted: {build_count}\n",
        f"- builds OK: {build_ok_count}\n",
        f"- runtime smoke requested: {smoke_req_count}\n",
        f"- runtime smoke attempted: {smoke_attempted_count}\n",
        f"- runtime smoke OK: {smoke_ok_count}\n",
        "\n",
    ]
    for res in results:
        status = (
            "OK"
            if res.export_exit_code == 0
            and res.generated_checks_ok
            and (not res.build_attempted or res.build_ok)
            and (not res.runtime_smoke_attempted or res.runtime_smoke_ok)
            else "WARN"
        )
        md_lines.append(f"## {res.project_name} [{status}]\n")
        md_lines.append(f"- project_dir: `{Path(res.project_dir).name}`\n")
        md_lines.append(f"- export_exit_code: `{res.export_exit_code}`\n")
        md_lines.append(f"- preflight issues: `{res.preflight_issue_count}`\n")
        md_lines.append(f"- post-export issues: `{res.post_issue_count}`\n")
        if res.build_attempted:
            md_lines.append(f"- build_exit_code: `{res.build_exit_code}`\n")
            md_lines.append(f"- build_summary: `{res.build_summary}`\n")
            for line in res.build_log_tail:
                md_lines.append(f"- build_tail: `{line}`\n")
        else:
            md_lines.append("- build: `not attempted`\n")
        if res.runtime_smoke_requested:
            md_lines.append(f"- runtime_smoke: `{res.runtime_smoke_summary}`\n")
            if res.runtime_smoke_artifact:
                md_lines.append(f"- runtime_artifact: `{Path(res.runtime_smoke_artifact).name}`\n")
        else:
            md_lines.append("- runtime_smoke: `not requested`\n")
        for check in res.generated_checks:
            md_lines.append(f"- {check}\n")
        md_lines.append("\n")

    md_path.write_text("".join(md_lines), encoding="utf-8")
    json_path.write_text(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path


def run_validation_suite(
    *,
    destination_root: Path,
    template_root: Path,
    log: Callable[[str], None] = print,
    build_projects: bool = False,
    smoke_run: bool = False,
) -> list[ValidationCaseResult]:
    """Generate the validation suite, run exports, and write a report."""

    projects = build_validation_suite(destination_root=destination_root, template_root=template_root, log=log)
    results: list[ValidationCaseResult] = []
    for project_dir in projects:
        project_file = project_dir / "project.ngpcraft"
        log(f"[QA-1] export {project_dir.name}")
        results.append(
            _run_one_project(
                project_file,
                log,
                build_projects=build_projects,
                smoke_run=smoke_run,
            )
        )
    md_path, json_path = _write_reports(destination_root, results)
    log(f"[QA-1] report: {md_path}")
    log(f"[QA-1] report: {json_path}")
    return results
