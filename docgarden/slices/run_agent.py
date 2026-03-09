from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable

from ..errors import DocgardenError
from ..files import atomic_write_text
from .run_status import SliceRunStatusRecord, _elapsed_seconds, _iso_now, _write_run_status


CODEX_ENV_DENYLIST = {
    "CODEX_CI",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_THREAD_ID",
}

DEFAULT_CODEX_EXEC_ARGS = (
    "--ephemeral",
    "-c",
    "mcp_servers.pencil.enabled=false",
    "-c",
    "mcp_servers.openaiDeveloperDocs.enabled=false",
    "-c",
    "sandbox_workspace_write.network_access=true",
)

RUN_STATUS_HEARTBEAT_SECONDS = 5.0


@dataclass(slots=True)
class AgentRunArtifact:
    prompt_path: Path
    schema_path: Path
    output_path: Path
    stdout_path: Path
    stderr_path: Path
    parsed_output: dict[str, Any]
    command: list[str]


def run_codex_agent(
    repo_root: Path,
    *,
    run_dir: Path,
    codex_bin: str,
    codex_args: list[str],
    model: str | None,
    prompt: str,
    schema: dict[str, Any],
    prefix: str,
    timeout_seconds: int | None,
    status_callback: Callable[..., None] | None = None,
) -> AgentRunArtifact:
    prompt_path = run_dir / f"{prefix}.prompt.txt"
    schema_path = run_dir / f"{prefix}.schema.json"
    output_path = run_dir / f"{prefix}.output.json"
    stdout_path = run_dir / f"{prefix}.stdout.txt"
    stderr_path = run_dir / f"{prefix}.stderr.txt"

    atomic_write_text(prompt_path, prompt)
    atomic_write_text(schema_path, json.dumps(schema, indent=2, sort_keys=True) + "\n")

    command = [
        codex_bin,
        "exec",
        "--full-auto",
        "-C",
        str(repo_root),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
    ]
    command.extend(DEFAULT_CODEX_EXEC_ARGS)
    if model:
        command.extend(["--model", model])
    command.extend(codex_args)
    command.append("-")

    atomic_write_text(stdout_path, "")
    atomic_write_text(stderr_path, "")

    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=repo_root,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                env=_build_codex_subprocess_env(),
            )
            started_at = _iso_now()
            started_monotonic = time.monotonic()
            if status_callback is not None:
                status_callback(
                    agent_pid=process.pid,
                    phase_started_at=started_at,
                    last_heartbeat_at=started_at,
                    elapsed_seconds=0.0,
                )
            stop_event = threading.Event()
            heartbeat_thread: threading.Thread | None = None
            if status_callback is not None:
                heartbeat_thread = threading.Thread(
                    target=_heartbeat_run_status,
                    args=(process, stop_event, status_callback, started_monotonic),
                    daemon=True,
                )
                heartbeat_thread.start()
            try:
                process.communicate(input=prompt, timeout=timeout_seconds)
                if status_callback is not None:
                    status_callback(
                        agent_pid=process.pid,
                        last_heartbeat_at=_iso_now(),
                        elapsed_seconds=_elapsed_seconds(started_monotonic),
                    )
            except subprocess.TimeoutExpired as exc:
                if status_callback is not None:
                    status_callback(
                        agent_pid=process.pid,
                        last_heartbeat_at=_iso_now(),
                        elapsed_seconds=_elapsed_seconds(started_monotonic),
                    )
                stop_event.set()
                process.kill()
                process.communicate()
                timeout_display = "the configured timeout"
                if timeout_seconds is not None:
                    timeout_display = f"{timeout_seconds} seconds"
                raise DocgardenError(
                    f"Codex agent run timed out for {prefix} after {timeout_display}. "
                    f"Partial logs were written to {stdout_path} and {stderr_path}."
                ) from exc
            finally:
                stop_event.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1)
    except FileNotFoundError as exc:
        raise DocgardenError(f"Could not find Codex CLI binary: {codex_bin}.") from exc

    if process.returncode != 0:
        raise DocgardenError(
            f"Codex agent run failed for {prefix} with exit code {process.returncode}. "
            f"See {stderr_path}."
        )
    if not output_path.exists():
        raise DocgardenError(
            f"Codex agent run for {prefix} did not write structured output to {output_path}."
        )

    try:
        parsed_output = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocgardenError(
            f"Structured output for {prefix} was not valid JSON: {output_path}."
        ) from exc
    if not isinstance(parsed_output, dict):
        raise DocgardenError(
            f"Structured output for {prefix} must be a JSON object: {output_path}."
        )

    return AgentRunArtifact(
        prompt_path=prompt_path,
        schema_path=schema_path,
        output_path=output_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        parsed_output=parsed_output,
        command=command,
    )


def make_status_callback(
    run_dir: Path,
    base_status: SliceRunStatusRecord,
) -> Callable[..., None]:
    def emit(**heartbeat_payload: Any) -> None:
        _write_run_status(run_dir, base_status.merged(**heartbeat_payload))

    return emit


def _heartbeat_run_status(
    process: subprocess.Popen[str],
    stop_event: threading.Event,
    status_callback: Callable[..., None],
    started_monotonic: float,
) -> None:
    while not stop_event.wait(RUN_STATUS_HEARTBEAT_SECONDS):
        if process.poll() is not None:
            return
        status_callback(
            agent_pid=process.pid,
            last_heartbeat_at=_iso_now(),
            elapsed_seconds=_elapsed_seconds(started_monotonic),
        )


def _build_codex_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    # Nested `codex exec` runs should not inherit the parent Codex session's
    # sandbox/thread controls, or the child can start in an unusable state.
    for key in CODEX_ENV_DENYLIST:
        env.pop(key, None)
    return env
