"""Model files read in a QGIS task, so QGIS never freezes while a large file is read: the
jobs are prepared on the main thread (``SectionDataProvider.unread``), run off it, and their
results handed to the provider on the main thread. One task runs at a time; QGIS's status
bar shows its progress with a Cancel button."""
from __future__ import annotations

from typing import Callable

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QObject, pyqtSignal

from .data import ReadJob, run_job

TASK_TITLE = "Reading models"


class ReadModelsTask(QgsTask):
    """Runs ``jobs`` in order; keeps the results of those read before a Cancel."""

    def __init__(self, jobs: list[ReadJob]):
        super().__init__(TASK_TITLE, QgsTask.Flag.CanCancel)
        self.jobs = jobs
        self.results: list[tuple[ReadJob, object]] = []
        self.current = jobs[0] if jobs else None

    def run(self) -> bool:
        for i, job in enumerate(self.jobs):
            if self.isCanceled():
                return False
            self.current = job
            try:
                self.results.append((job, run_job(job)))
            except Exception:                   # noqa: BLE001 - drawing the section says why
                pass
            self.setProgress(100.0 * (i + 1) / len(self.jobs))
        return not self.isCanceled()


class _Batch:
    def __init__(self, jobs: list[ReadJob]):
        self.jobs = jobs
        self.ids = {j.dataset_id for j in jobs}
        self.done: list[Callable[[bool], None]] = []
        self.task: ReadModelsTask | None = None


class ModelReader(QObject):
    """Reads models for the section panel and the 3D view in the background."""

    #: (read so far, of how many, the profile being read) while a task runs
    progress = pyqtSignal(int, int, str)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self._batches: list[_Batch] = []        # the first one runs

    @property
    def busy(self) -> bool:
        return bool(self._batches)

    def request(self, profile_ids, done: Callable[[bool], None]) -> bool:
        """Read what ``profile_ids`` still need, then call ``done(True)`` (``False``: the
        reading was cancelled). False when there is nothing to read: ``done`` is not
        called."""
        wanted = self.provider.unread(profile_ids)
        if not wanted:
            return False
        queued = set().union(*(b.ids for b in self._batches)) if self._batches else set()
        new = [j for j in wanted if j.dataset_id not in queued]
        if new:
            self._batches.append(_Batch(new))
        else:                                   # all on their way: the last batch with one
            ids = {j.dataset_id for j in wanted}
            last = max(i for i, b in enumerate(self._batches) if b.ids & ids)
            self._batches[last].done.append(done)
            return True
        self._batches[-1].done.append(done)
        if len(self._batches) == 1:
            self._start()
        return True

    def cancel(self) -> None:
        """Stop reading: the running task is cancelled, the queued ones dropped (their
        ``done`` called with False)."""
        for batch in self._batches[1:]:
            for done in batch.done:
                done(False)
        del self._batches[1:]
        if self._batches and self._batches[0].task is not None:
            self._batches[0].task.cancel()

    def _start(self) -> None:
        batch = self._batches[0]
        task = batch.task = ReadModelsTask(batch.jobs)
        total = len(batch.jobs)
        task.progressChanged.connect(
            lambda p: self.progress.emit(round(p * total / 100.0), total,
                                         task.current.profile_name if task.current else ""))
        task.taskCompleted.connect(lambda: self._finished(batch, True))
        task.taskTerminated.connect(lambda: self._finished(batch, False))
        self.progress.emit(0, total, batch.jobs[0].profile_name)
        QgsApplication.taskManager().addTask(task)

    def _finished(self, batch: _Batch, ok: bool) -> None:
        for job, result in batch.task.results:
            self.provider.take(job, result)
        if self._batches and self._batches[0] is batch:
            self._batches.pop(0)
        for done in batch.done:
            done(ok)
        if self._batches and self._batches[0].task is None:
            self._start()
