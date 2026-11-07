"""Private, schema-versioned manifests. One process, OS lock, atomic durable writes."""

import copy
import fcntl
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class DomainError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(code)


def uid():
    return uuid4().hex


class Repository:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()

    def path(self, work_id):
        if not re.fullmatch(r"[a-f0-9]{32}", work_id):
            raise DomainError("NOT_FOUND", "作品不存在", 404)
        return self.root / f"{work_id}.json"

    @contextmanager
    def locked(self):
        with self.lock, (self.root / ".write.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read(self, work_id):
        try:
            value = json.loads(self.path(work_id).read_text())
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != 1
                or value.get("id") != work_id
            ):
                raise ValueError()
            for key in ("sources", "claims", "claim_history", "jobs", "budget_entries"):
                if not isinstance(value.get(key), list):
                    raise ValueError()
            if not value["sources"] or type(value.get("revision")) is not int:
                raise ValueError()
            from .schemas import WorkData

            WorkData.model_validate(
                {
                    **value,
                    "jobs": [
                        {
                            k: v
                            for k, v in job.items()
                            if k in {"id", "operation_id", "status", "error", "kind"}
                        }
                        for job in value["jobs"]
                    ],
                    "budget": dict(
                        limit_micro=1_000_000, settled_micro=0, reserved_micro=0, available_micro=0
                    ),
                }
            )
            for entry in value["budget_entries"]:
                if entry.get("status") not in {"reserved", "settled", "uncertain"}:
                    raise ValueError()
                if type(entry.get("reserved_micro")) is not int or entry["reserved_micro"] < 0:
                    raise ValueError()
                if entry["status"] == "settled" and (
                    type(entry.get("actual_micro")) is not int or entry["actual_micro"] < 0
                ):
                    raise ValueError()
            return value
        except FileNotFoundError:
            raise DomainError("NOT_FOUND", "作品不存在", 404) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DomainError(
                "DATA_DAMAGED", "作品数据无法读取，原文件已保留，请先恢复备份", 503
            ) from None

    def _write(self, work):
        path = self.path(work["id"])
        descriptor, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(work, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def create(self, material):
        work = dict(
            schema_version=1,
            id=uid(),
            owner_id="local",
            revision=1,
            stage="material",
            sources=[dict(material, revision=1)],
            claims=[],
            claim_history=[],
            jobs=[],
            budget_entries=[],
        )
        with self.locked():
            self._write(work)
        return work

    def get(self, work_id):
        with self.locked():
            return self._read(work_id)

    def list(self):
        # Corrupt records must be visible as errors, never silently skipped.
        with self.locked():
            return [self._read(path.stem) for path in sorted(self.root.glob("*.json"))]

    def mutate(self, work_id, expected, change):
        with self.locked():
            work = self._read(work_id)
            if expected is not None and expected != work["revision"]:
                raise DomainError("REVISION_CONFLICT", "作品已在别处更新，请重新载入后再编辑", 409)
            work = copy.deepcopy(work)
            change(work)
            work["revision"] += 1
            self._write(work)
            return work

    def recover(self):
        for work in self.list():
            if not any(job["status"] in {"pending", "running"} for job in work["jobs"]):
                continue

            def interrupt(value):
                for job in value["jobs"]:
                    if job["status"] in {"pending", "running"}:
                        job["status"] = "interrupted"
                        for entry in value["budget_entries"]:
                            if entry["job_id"] == job["id"] and entry["status"] != "settled":
                                entry["status"] = (
                                    "uncertain" if entry.get("sent", True) else "reserved"
                                )
                        job["error"] = {
                            "code": "INTERRUPTED",
                            "message": "生成已中断，请核对结果后继续；不会自动再次调用",
                        }
                # Submitted/unknown reservations stay occupied after restart.

            self.mutate(work["id"], None, interrupt)
