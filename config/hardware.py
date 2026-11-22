"""Hardware detection used to show runtime info and pick safe defaults."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class GPUInfo:
    name: str
    total_mb: int
    used_mb: int

    @property
    def free_mb(self) -> int:
        return self.total_mb - self.used_mb


def detect_gpus() -> list[GPUInfo]:
    """Query NVIDIA GPUs via nvidia-smi. Returns [] when unavailable."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            try:
                gpus.append(GPUInfo(parts[0], int(parts[1]), int(parts[2])))
            except ValueError:
                continue
    return gpus


def hardware_summary() -> str:
    gpus = detect_gpus()
    if not gpus:
        return "No NVIDIA GPU detected (CPU inference only)."
    return "; ".join(f"{g.name}: {g.used_mb}/{g.total_mb} MiB VRAM used" for g in gpus)
