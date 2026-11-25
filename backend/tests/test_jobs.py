"""Jobs v2: cancellation, resource admission and restart recovery."""
from __future__ import annotations

import time

import pytest

from app import jobs


@pytest.fixture(autouse=True)
def clean_registry():
    jobs.JOBS.clear()
    jobs._FUNCS.clear()
    yield
    jobs.cancel_pending_save()
    jobs.JOBS.clear()
    jobs._FUNCS.clear()


def wait(jid: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = jobs.snapshot(jid)
        assert snap is not None
        if snap["status"] in ("done", "error", "canceled", "interrupted"):
            return snap
        time.sleep(0.02)
    raise AssertionError(f"任务 {jid} 在 {timeout}s 内没有结束")


class TestRun:
    def test_result_is_stored(self):
        jid = jobs.create("build", "cpu")
        jobs.run(jid, lambda progress: {"name": "x"})
        snap = wait(jid)
        assert snap["status"] == "done"
        assert snap["result"] == {"name": "x"}
        assert snap["progress"] == 1.0

    def test_exception_becomes_an_error_job(self):
        jid = jobs.create("build", "cpu")

        def boom(_progress):
            raise RuntimeError("歌词源不可用")

        jobs.run(jid, boom)
        snap = wait(jid)
        assert snap["status"] == "error"
        assert "歌词源不可用" in snap["error"]

    def test_progress_moves_the_job_out_of_queued(self):
        jid = jobs.create("build", "cpu")

        def work(progress):
            progress(0.4, "对齐中")
            assert jobs.get(jid)["status"] == "running"
            return {}

        jobs.run(jid, work)
        assert wait(jid)["status"] == "done"


class TestCancel:
    def test_a_queued_job_is_canceled_before_it_starts(self):
        blocker = jobs.create("build", "cpu")
        release = __import__("threading").Event()
        ran = []

        jobs.run(blocker, lambda progress: (release.wait(3), ran.append("blocker"))[1])
        in_queue = jobs.create("build", "cpu")
        jobs.run(in_queue, lambda progress: (ran.append("second"), {})[1])

        assert jobs.cancel(in_queue) is True
        assert jobs.get(in_queue)["status"] == "canceled"
        release.set()
        wait(blocker)
        time.sleep(0.2)
        assert ran == ["blocker"], "取消的排队任务不该被执行"

    def test_a_running_job_stops_at_its_next_progress(self):
        jid = jobs.create("build", "cpu")

        def loop(progress):
            for i in range(200):
                progress(i / 200, f"第 {i} 步")
                time.sleep(0.01)
            return {"finished": True}

        jobs.run(jid, loop)
        deadline = time.time() + 3
        while time.time() < deadline and jobs.get(jid)["status"] != "running":
            time.sleep(0.01)
        jobs.cancel(jid)
        snap = wait(jid)
        assert snap["status"] == "canceled"
        assert snap["result"] is None

    def test_canceling_a_finished_job_is_a_no_op(self):
        jid = jobs.create("build", "cpu")
        jobs.run(jid, lambda progress: {})
        wait(jid)
        assert jobs.cancel(jid) is False
        assert jobs.get(jid)["status"] == "done"


class TestResourceAdmission:
    def test_cpu_jobs_run_one_at_a_time(self):
        order: list[str] = []
        release = __import__("threading").Event()

        first = jobs.create("build", "cpu")
        jobs.run(first, lambda p: (release.wait(3), order.append("first"), {})[2])
        second = jobs.create("build", "cpu")
        jobs.run(second, lambda p: (order.append("second"), {})[1])

        time.sleep(0.4)
        assert order == [], "第二个 cpu 任务不该在第一个结束前开始"
        release.set()
        wait(first)
        wait(second)
        assert order == ["first", "second"]

    def test_net_jobs_do_not_block_cpu(self):
        order: list[str] = []
        release = __import__("threading").Event()

        cpu = jobs.create("build", "cpu")
        jobs.run(cpu, lambda p: (release.wait(3), order.append("cpu"), {})[2])
        net = jobs.create("install", "net")
        jobs.run(net, lambda p: (order.append("net"), {})[1])

        wait(net)
        assert order == ["net"]
        release.set()
        wait(cpu)


class TestPersistence:
    def test_unfinished_jobs_come_back_as_interrupted(self, tmp_path, monkeypatch):
        state = tmp_path / "jobs.json"
        monkeypatch.setattr(jobs, "STATE_FILE", state)

        jid = jobs.create("build", "cpu")
        jobs.update(jid, 0.3, "转写中")
        jobs.cancel_pending_save()
        jobs._save_now()
        jobs.JOBS.clear()

        assert jobs.load_state() == 1
        snap = jobs.snapshot(jid)
        assert snap is not None
        assert snap["status"] == "interrupted"
        assert "重新生成" in snap["message"]

    def test_finished_jobs_keep_their_result(self, tmp_path, monkeypatch):
        state = tmp_path / "jobs.json"
        monkeypatch.setattr(jobs, "STATE_FILE", state)

        jid = jobs.create("export", "export")
        jobs.finish(jid, {"file": "a.mp4"})
        # the debounced timer can fire after the clear and overwrite the file
        jobs.cancel_pending_save()
        jobs._save_now()
        jobs.JOBS.clear()

        jobs.load_state()
        snap = jobs.snapshot(jid)
        assert snap["status"] == "done"
        assert snap["result"] == {"file": "a.mp4"}

    def test_a_corrupt_state_file_is_ignored(self, tmp_path, monkeypatch):
        state = tmp_path / "jobs.json"
        state.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(jobs, "STATE_FILE", state)
        assert jobs.load_state() == 0
