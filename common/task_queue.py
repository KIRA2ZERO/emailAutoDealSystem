import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional


TaskHandler = Callable[..., Awaitable[Any]]
Logger = Callable[[str], None]


@dataclass
class DownloadTask:
    source: str
    subject: str
    payload: Any
    email_uid: int
    handler: TaskHandler
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"
    attempts: int = 0
    max_retries: int = 2
    retry_delay: int = 60
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_error: Optional[str] = None
    log_file: Optional[str] = None

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end_time = self.finished_at or time.time()
        return end_time - self.started_at

    def to_record(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "subject": self.subject,
            "payload": self.payload,
            "email_uid": self.email_uid,
            "status": self.status,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_error": self.last_error,
            "log_file": self.log_file,
        }

    @classmethod
    def from_record(cls, record: Dict[str, Any], handler: TaskHandler):
        task = cls(
            source=record["source"],
            subject=record.get("subject", ""),
            payload=record.get("payload"),
            email_uid=record.get("email_uid", 0),
            handler=handler,
            task_id=record.get("task_id") or uuid.uuid4().hex[:12],
            max_retries=record.get("max_retries", 2),
            retry_delay=record.get("retry_delay", 60),
        )
        task.status = record.get("status", "queued")
        task.attempts = record.get("attempts", 0)
        task.created_at = record.get("created_at", time.time())
        task.started_at = record.get("started_at")
        task.finished_at = record.get("finished_at")
        task.last_error = record.get("last_error")
        task.log_file = record.get("log_file")
        return task


class TaskManager:
    def __init__(
        self,
        worker_count: int = 1,
        monitor_interval: int = 30,
        logger: Optional[Logger] = None,
        state_file: Optional[str] = None,
        handlers: Optional[Dict[str, TaskHandler]] = None,
        log_dir: Optional[str] = None,
    ):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.registry: Dict[str, DownloadTask] = {}
        self.worker_count = worker_count
        self.monitor_interval = monitor_interval
        self.logger = logger or print
        self.state_file = Path(state_file) if state_file else None
        self.handlers = handlers or {}
        self.log_dir = Path(log_dir) if log_dir else None
        self._state_lock = asyncio.Lock()
        self._background_tasks = []

    async def start(self):
        await self.load_state()
        for index in range(self.worker_count):
            self._background_tasks.append(
                asyncio.create_task(self._worker(f"worker-{index + 1}"))
            )
        self._background_tasks.append(asyncio.create_task(self._monitor()))
        self.logger(
            f"任务队列已启动，worker={self.worker_count}, "
            f"monitor_interval={self.monitor_interval}s"
        )

    async def enqueue(self, task: DownloadTask):
        self.registry[task.task_id] = task
        self._ensure_task_log_file(task)
        task.status = "queued"
        await self.queue.put(task)
        await self.save_state()
        self._log_task(task, f"任务已入队，queue_size={self.queue.qsize()}")

    async def load_state(self):
        if not self.state_file or not self.state_file.exists():
            return
        try:
            with self.state_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            self.logger(f"任务状态文件读取失败，将从空队列启动: {exc}")
            return

        restored = 0
        stale_running = 0
        skipped = 0
        for record in data.get("tasks", []):
            source = record.get("source")
            handler = self.handlers.get(source)
            if not handler:
                skipped += 1
                self.logger(f"跳过未知任务处理器 source={source} task_id={record.get('task_id')}")
                continue
            task = DownloadTask.from_record(record, handler)
            self._ensure_task_log_file(task)
            self.registry[task.task_id] = task
            if task.status == "running":
                task.status = "failed"
                task.finished_at = time.time()
                task.last_error = "服务启动时发现任务仍为 running，未自动重试以避免重复下载"
                self._log_task(task, task.last_error)
                stale_running += 1
            elif task.status in {"queued", "retrying"}:
                task.status = "queued"
                task.started_at = None
                task.finished_at = None
                await self.queue.put(task)
                restored += 1
        self.logger(
            f"任务状态文件已加载: total={len(self.registry)} "
            f"restored={restored} stale_running={stale_running} skipped={skipped}"
        )
        if restored or stale_running:
            await self.save_state()

    async def save_state(self):
        if not self.state_file:
            return
        async with self._state_lock:
            data = {
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tasks": [task.to_record() for task in self.registry.values()],
            }
            await asyncio.to_thread(self._write_state_file, data)

    def _write_state_file(self, data: Dict[str, Any]):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        with tmp_file.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_file, self.state_file)

    async def _worker(self, worker_name: str):
        self.logger(f"{worker_name} 已启动")
        while True:
            task = await self.queue.get()
            try:
                await self._run_task(worker_name, task)
            finally:
                self.queue.task_done()

    async def _run_task(self, worker_name: str, task: DownloadTask):
        task.attempts += 1
        task.status = "running"
        task.started_at = time.time()
        task.finished_at = None
        task.last_error = None
        await self.save_state()
        self._log_task(task, f"{worker_name} 开始执行，第 {task.attempts} 次尝试")

        try:
            result = await task.handler(task.payload, log_file=task.log_file)
            returncode = self._extract_returncode(result)
            if returncode not in (None, 0):
                raise RuntimeError(f"download command exited with code {returncode}")

            task.status = "success"
            task.finished_at = time.time()
            await self.save_state()
            self._log_task(task, f"任务完成，耗时 {task.duration:.1f}s")
        except Exception as exc:
            task.last_error = str(exc)
            task.finished_at = time.time()
            if task.attempts <= task.max_retries:
                task.status = "retrying"
                await self.save_state()
                self._log_task(
                    task,
                    f"任务失败，{task.retry_delay}s 后重试: {task.last_error}",
                )
                asyncio.create_task(self._retry_later(task))
            else:
                task.status = "failed"
                await self.save_state()
                self._log_task(
                    task,
                    f"任务最终失败，已尝试 {task.attempts} 次: {task.last_error}",
                )

    async def _retry_later(self, task: DownloadTask):
        await asyncio.sleep(task.retry_delay)
        task.status = "queued"
        await self.queue.put(task)
        await self.save_state()
        self._log_task(task, f"重试任务已重新入队，queue_size={self.queue.qsize()}")

    async def _monitor(self):
        while True:
            await asyncio.sleep(self.monitor_interval)
            counts = self.status_counts()
            self.logger(
                "任务队列状态: "
                f"queued={counts.get('queued', 0)} "
                f"running={counts.get('running', 0)} "
                f"retrying={counts.get('retrying', 0)} "
                f"success={counts.get('success', 0)} "
                f"failed={counts.get('failed', 0)} "
                f"queue_size={self.queue.qsize()} "
                f"total={len(self.registry)}"
            )
            for task in self.active_tasks():
                self._log_task(
                    task,
                    f"当前状态={task.status}, attempts={task.attempts}, "
                    f"运行/等待 {task.duration:.1f}s",
                )

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for task in self.registry.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        return counts

    def active_tasks(self):
        return [
            task
            for task in self.registry.values()
            if task.status in {"queued", "running", "retrying"}
        ]

    def _log_task(self, task: DownloadTask, message: str):
        self.logger(
            f"task_id={task.task_id} source={task.source} "
            f"uid={task.email_uid} status={task.status} log={task.log_file} {message}"
        )

    def _ensure_task_log_file(self, task: DownloadTask):
        if task.log_file or not self.log_dir:
            return
        task_log_dir = self.log_dir / task.source
        task_log_dir.mkdir(parents=True, exist_ok=True)
        task.log_file = str(task_log_dir / f"{task.task_id}.log")

    @staticmethod
    def _extract_returncode(result):
        if result is None:
            return None
        if isinstance(result, int):
            return result
        if isinstance(result, dict):
            return result.get("returncode")
        return getattr(result, "returncode", None)
