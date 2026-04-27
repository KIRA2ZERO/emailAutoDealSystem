import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional


TaskHandler = Callable[[Any], Awaitable[Any]]
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

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end_time = self.finished_at or time.time()
        return end_time - self.started_at


class TaskManager:
    def __init__(
        self,
        worker_count: int = 1,
        monitor_interval: int = 30,
        logger: Optional[Logger] = None,
    ):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.registry: Dict[str, DownloadTask] = {}
        self.worker_count = worker_count
        self.monitor_interval = monitor_interval
        self.logger = logger or print
        self._background_tasks = []

    def start(self):
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
        task.status = "queued"
        await self.queue.put(task)
        self._log_task(task, f"任务已入队，queue_size={self.queue.qsize()}")

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
        self._log_task(task, f"{worker_name} 开始执行，第 {task.attempts} 次尝试")

        try:
            result = await task.handler(task.payload)
            returncode = self._extract_returncode(result)
            if returncode not in (None, 0):
                raise RuntimeError(f"download command exited with code {returncode}")

            task.status = "success"
            task.finished_at = time.time()
            self._log_task(task, f"任务完成，耗时 {task.duration:.1f}s")
        except Exception as exc:
            task.last_error = str(exc)
            task.finished_at = time.time()
            if task.attempts <= task.max_retries:
                task.status = "retrying"
                self._log_task(
                    task,
                    f"任务失败，{task.retry_delay}s 后重试: {task.last_error}",
                )
                asyncio.create_task(self._retry_later(task))
            else:
                task.status = "failed"
                self._log_task(
                    task,
                    f"任务最终失败，已尝试 {task.attempts} 次: {task.last_error}",
                )

    async def _retry_later(self, task: DownloadTask):
        await asyncio.sleep(task.retry_delay)
        task.status = "queued"
        await self.queue.put(task)
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
            f"uid={task.email_uid} status={task.status} {message}"
        )

    @staticmethod
    def _extract_returncode(result):
        if result is None:
            return None
        if isinstance(result, int):
            return result
        if isinstance(result, dict):
            return result.get("returncode")
        return getattr(result, "returncode", None)
