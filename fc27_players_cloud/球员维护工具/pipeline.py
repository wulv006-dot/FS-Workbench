"""可单步或串行执行的本地流水线。"""

from __future__ import annotations

import traceback
import uuid
from pathlib import Path
from threading import Event, Lock
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from .adapters import AdapterBlocked, AdapterContext, AdapterSkipped, StepAdapter, default_adapters
from .models import PipelineConfig, RunRecord, StepName, StepResult, StepStatus, utc_now_iso
from .storage import JsonlLogger, LocalStore, atomic_write_json, redact, redact_text


ProgressCallback = Callable[[str, object], None]


class PipelineRunner:
    """在独立运行目录中编排适配器，不覆盖源文件。"""

    def __init__(
        self,
        store: LocalStore,
        adapters: Optional[Mapping[StepName, StepAdapter]] = None,
        progress: Optional[ProgressCallback] = None,
        backend: object = None,
    ) -> None:
        self.store = store
        self.adapters: Dict[StepName, StepAdapter] = dict(adapters or default_adapters())
        self.progress = progress
        self.backend = backend
        self.stop_event = Event()
        self._lock = Lock()
        self._run_guard = Lock()
        self._active_record: Optional[RunRecord] = None

    def request_stop(self) -> None:
        """设置停止标记；之后不会启动新步骤。"""

        self.stop_event.set()
        self._emit("stop_requested", {"message": "已请求停止；不会启动新的步骤"})

    def reset_stop(self) -> None:
        self.stop_event.clear()

    def run_step(self, step: str | StepName, config: PipelineConfig) -> RunRecord:
        normalized = config.normalized()
        step_name = self._coerce_step(step)
        return self._run(normalized, [step_name])

    def run_all(self, config: PipelineConfig) -> RunRecord:
        normalized = config.normalized()
        steps = [self._coerce_step(item) for item in normalized.selected_steps]
        return self._run(normalized, steps)

    def _run(self, config: PipelineConfig, steps: List[StepName]) -> RunRecord:
        if not self._run_guard.acquire(blocking=False):
            raise RuntimeError("已有流水线正在运行，未启动并发运行")
        try:
            return self._run_locked(config, steps)
        finally:
            self._run_guard.release()

    def _run_locked(self, config: PipelineConfig, steps: List[StepName]) -> RunRecord:
        with self._lock:
            self.reset_stop()
            run_id, run_dir = self.store.create_run_dir(config.output_root)
            record = RunRecord(run_id=run_id, run_dir=str(run_dir), started_at=utc_now_iso())
            self._active_record = record
        logger = JsonlLogger(run_dir / "run.log.jsonl")
        logger.write("INFO", "run_started", "流水线运行开始", run_id=run_id, step_count=len(steps))
        self._write_checkpoint(run_dir, record)
        self._emit("run_started", record)

        for index, step in enumerate(steps):
            if self.stop_event.is_set():
                self._append_stopped(record, steps[index:], logger)
                self._write_checkpoint(run_dir, record)
                break
            result = self._run_one(step, config, run_dir, logger, record)
            record.steps.append(result)
            self._write_checkpoint(run_dir, record)
            self._emit("step_finished", result)
            if result.status in {StepStatus.FAILED.value, StepStatus.BLOCKED.value, StepStatus.STOPPED.value}:
                # 串行模式遇到安全阻断/失败后不发起后续动作。
                if index + 1 < len(steps):
                    self._append_unstarted(record, steps[index + 1 :], logger, result.status)
                    self._write_checkpoint(run_dir, record)
                break

        if self.stop_event.is_set():
            record.status = StepStatus.STOPPED.value
        elif any(item.status == StepStatus.FAILED.value for item in record.steps):
            record.status = StepStatus.FAILED.value
        elif any(item.status == StepStatus.BLOCKED.value for item in record.steps):
            record.status = StepStatus.BLOCKED.value
        elif any(item.status == StepStatus.STOPPED.value for item in record.steps):
            record.status = StepStatus.STOPPED.value
        else:
            record.status = StepStatus.SUCCESS.value
        record.finished_at = utc_now_iso()
        logger.write("INFO", "run_finished", "流水线运行结束", run_id=run_id, status=record.status)
        self._write_checkpoint(run_dir, record)
        self.store.append_history(record)
        self._emit("run_finished", record)
        with self._lock:
            self._active_record = None
        return record

    def _run_one(self, step: StepName, config: PipelineConfig, run_dir: Path, logger: JsonlLogger, record: RunRecord) -> StepResult:
        started = utc_now_iso()
        adapter = self.adapters.get(step)
        logger.write("INFO", "step_started", "步骤开始", step=step.value)
        self._emit("step_started", step.value)
        if adapter is None:
            result = StepResult(
                step=step.value,
                status=StepStatus.BLOCKED.value,
                started_at=started,
                finished_at=utc_now_iso(),
                message="未注册步骤适配器",
                error_code="ADAPTER_MISSING",
                error_message="未注册步骤适配器",
            )
            logger.write("WARNING", "step_blocked", result.message, step=step.value, error_code=result.error_code)
            return result
        if self.stop_event.is_set():
            return self._stopped_result(step, started, logger)
        context = AdapterContext(
            config=config,
            run_dir=run_dir,
            logger=logger,
            stop_event=self.stop_event,
            previous_results={item.step: item for item in record.steps},
            backend=self.backend,
        )
        try:
            data = adapter.execute(context)
            result = StepResult(
                step=step.value,
                status=StepStatus.SUCCESS.value,
                started_at=started,
                finished_at=utc_now_iso(),
                message="步骤完成",
                result=redact(data),
            )
            logger.write("INFO", "step_succeeded", result.message, step=step.value, result=result.result)
            return result
        except AdapterBlocked as exc:
            status = StepStatus.STOPPED.value if exc.code == "STOP_REQUESTED" else StepStatus.BLOCKED.value
            result = StepResult(
                step=step.value,
                status=status,
                started_at=started,
                finished_at=utc_now_iso(),
                message=exc.message,
                result=redact(exc.details),
                error_code=exc.code,
                error_message=exc.message,
            )
            logger.write("WARNING", "step_blocked", exc.message, step=step.value, error_code=exc.code, details=exc.details)
            return result
        except AdapterSkipped as exc:
            result = StepResult(
                step=step.value,
                status=StepStatus.SKIPPED.value,
                started_at=started,
                finished_at=utc_now_iso(),
                message=exc.message,
                result=redact(exc.details),
                error_code=exc.code,
            )
            logger.write("INFO", "step_skipped", exc.message, step=step.value, error_code=exc.code)
            return result
        except Exception as exc:  # pragma: no cover - 使用专门测试适配器覆盖主要路径
            result = StepResult(
                step=step.value,
                status=StepStatus.FAILED.value,
                started_at=started,
                finished_at=utc_now_iso(),
                message="步骤发生未预期错误",
                error_code="UNEXPECTED_ERROR",
                error_message=redact_text(exc),
            )
            logger.write("ERROR", "step_failed", result.message, step=step.value, error_code=result.error_code)
            logger.write("DEBUG", "step_traceback", "内部调试信息", step=step.value, traceback=redact_text(traceback.format_exc()))
            return result

    def _append_unstarted(self, record: RunRecord, steps: Iterable[StepName], logger: JsonlLogger, reason: str) -> None:
        for step in steps:
            result = StepResult(
                step=step.value,
                status=StepStatus.SKIPPED.value,
                started_at=utc_now_iso(),
                finished_at=utc_now_iso(),
                message=f"前一步骤{reason}，未启动此步骤",
                error_code="UPSTREAM_NOT_CONTINUED",
            )
            record.steps.append(result)
            logger.write("INFO", "step_skipped", result.message, step=step.value)
            self._emit("step_finished", result)

    def _append_stopped(self, record: RunRecord, steps: Iterable[StepName], logger: JsonlLogger) -> None:
        self._append_unstarted(record, steps, logger, "用户请求停止")
        record.status = StepStatus.STOPPED.value

    def _stopped_result(self, step: StepName, started: str, logger: JsonlLogger) -> StepResult:
        result = StepResult(
            step=step.value,
            status=StepStatus.STOPPED.value,
            started_at=started,
            finished_at=utc_now_iso(),
            message="用户已请求停止，未发起步骤动作",
            error_code="STOP_REQUESTED",
            error_message="用户已请求停止，未发起步骤动作",
        )
        logger.write("INFO", "step_stopped", result.message, step=step.value)
        return result

    def _coerce_step(self, value: str | StepName) -> StepName:
        try:
            return value if isinstance(value, StepName) else StepName(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(f"未知流水线步骤: {value}") from exc

    def _emit(self, event: str, payload: object) -> None:
        if self.progress:
            try:
                self.progress(event, payload)
            except Exception:
                # GUI 回调失败不应改变文件流水线结果。
                pass

    @staticmethod
    def _write_checkpoint(run_dir: Path, record: RunRecord) -> None:
        """每步更新一次原子 checkpoint，崩溃后仍可查看已完成范围。"""

        atomic_write_json(run_dir / "run.json", record.to_dict())
