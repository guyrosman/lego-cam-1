from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageManager:
    output_dir: Path
    min_free_mb: int

    def ensure_free_space(self) -> None:
        """
        Ensure at least min_free_mb is available on the filesystem holding output_dir.
        Deletes oldest files until the threshold is met or nothing remains.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        while self._free_mb() < self.min_free_mb:
            oldest = self._oldest_video()
            if oldest is None:
                log.warning(
                    "Low disk space (free=%dMB) but no files to delete",
                    self._free_mb(),
                )
                return
            try:
                log.warning("Deleting oldest segment to free space: %s", oldest)
                oldest.unlink(missing_ok=True)
            except Exception:
                log.exception("Failed deleting %s", oldest)
                return
        log.debug("Disk space OK (free=%dMB, min=%dMB)", self._free_mb(), self.min_free_mb)

    def list_segments(self) -> list[Path]:
        if not self.output_dir.exists():
            return []
        vids = [p for p in self.output_dir.glob("*.mp4") if p.is_file()]
        vids.sort(key=lambda p: p.stat().st_mtime)
        return vids

    def _oldest_video(self) -> Path | None:
        segs = self.list_segments()
        return segs[0] if segs else None

    def _free_mb(self) -> int:
        usage = shutil.disk_usage(self.output_dir)
        return int(usage.free // (1024 * 1024))

