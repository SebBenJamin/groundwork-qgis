"""The 3D view's slow part, computed in a QGIS task: the point clouds and contour lines of
the chosen models that have no file yet. ``pending_3d`` lists them on the main thread (with
plain copies of what they need), ``run_job3d`` computes one anywhere; filling the 3D layers
afterwards (``view3d_layers.sync``) only picks up the files."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from qgis.core import QgsTask

from . import view3d_layers as v3

TASK_TITLE = "Preparing 3D"


@dataclass
class Job3D:
    kind: str                       # "cloud" or "contours"
    path: Path
    name: str
    crs_authid: str
    profile: object                 # a copy of the Profile
    dataset: object
    section_layer: object           # its mesh (never changed in place) and a copy of its style
    topo: object


def pending_3d(store, provider, project) -> list[Job3D]:
    """The clouds and contour lines the current 3D choice needs and that have no file yet
    (main thread; the chosen models must have been read)."""
    from ..section.data import SectionLayer
    choice = v3.read_choice(project)
    jobs, topos = [], {}
    for profile, d, la in v3._gather(store, provider, choice):
        if not v3._shown(la):
            continue
        if profile.id not in topos:
            topos[profile.id] = v3._surface_line(provider, profile.id)
        topo = topos[profile.id]
        look = choice.look_of(d.id)
        copy = SectionLayer(la.dataset, la.mesh, replace(la.style), la.error)
        mine = replace(profile, xy=profile.xy.copy(), metadata=dict(profile.metadata))
        if look == "cloud" or (look == "section" and la.style.mode in v3._SMOOTH):
            path = v3.cloud_path(store, d.id, profile, la, topo)
            if not path.exists():
                jobs.append(Job3D("cloud", path, d.name or d.id, store.crs_authid, mine, d,
                                  copy, topo))
        if look != "picture" and la.style.mode in v3._LINES:
            path = v3.contours_path(store, d.id, v3.contour_signature(profile, d, la, topo))
            if not path.exists():
                jobs.append(Job3D("contours", path, d.name or d.id, store.crs_authid, mine, d,
                                  copy, topo))
    return jobs


def run_job3d(job: Job3D) -> None:
    """Write the job's file (any thread); a cloud with no points writes none."""
    if job.kind == "cloud":
        v3._write_cloud(job.path, job.crs_authid, job.profile, job.section_layer, job.topo)
    else:
        v3._contour_rows(job.path, job.profile, job.dataset, job.section_layer, job.topo)


class Prepare3DTask(QgsTask):
    def __init__(self, jobs: list[Job3D]):
        super().__init__(TASK_TITLE, QgsTask.Flag.CanCancel)
        self.jobs = jobs
        self.errors: list[str] = []

    def run(self) -> bool:
        for i, job in enumerate(self.jobs):
            if self.isCanceled():
                return False
            try:
                run_job3d(job)
            except Exception as exc:            # noqa: BLE001 - the fill logs it again
                self.errors.append(f"{job.name}: {exc}")
            self.setProgress(100.0 * (i + 1) / len(self.jobs))
        return True
