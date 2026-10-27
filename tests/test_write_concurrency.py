"""并发写入回归测试。

真实事故（2026-10-27 review 实测）：4 个进程各写 25 条 journal，落盘只剩
**25 条**（丢 75%），``food_cache.json`` 同样丢 75%。

根因是 ``os.replace`` 只保证**文件不损坏**，不保证**不丢更新**：两个进程同时
「读 → 改 → 原子替换」时，后写的会把先写的整份覆盖掉。

后果比「少记一条微量元素」严重得多：journal 丢了补剂记录 → 幂等检查认为
「今天没记过」→ 下一次定时任务重复写入 MFP，热量直接翻倍。

修法是 ``fcntl.flock`` 独占锁，且必须锁**独立的锁文件**——目标文件是
``tempfile`` + ``os.replace`` 换出来的，inode 每次都变，锁在旧 inode 上等于没锁。
"""

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mfp_adapter import MFPAdapter, _file_lock

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROCS = 4
ENTRIES_PER_PROC = 15
EXPECTED = PROCS * ENTRIES_PER_PROC

_JOURNAL_WRITER = """
import sys
from mfp_adapter import MFPAdapter

journal_file, tag, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
a = MFPAdapter.__new__(MFPAdapter)
a.JOURNAL_FILE = journal_file
a._JOURNAL_MAX_ENTRIES = 100000
for i in range(count):
    a._log_to_local_journal("2026-01-01", "Lunch", [{"name": f"{tag}-{i}", "calories": 1}])
"""

_CACHE_WRITER = """
import sys
import time
from mfp_adapter import MFPAdapter

cache_file, tag, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
a = MFPAdapter.__new__(MFPAdapter)
a.FOOD_CACHE_FILE = cache_file
for i in range(count):
    a._food_cache = {f"{tag}-{i}": {"id": f"id-{tag}-{i}", "version": 1, "calories": 10}}
    a._save_food_cache()
    time.sleep(0.005)
"""


def _run_parallel(script: str, target: str) -> None:
    """同时拉起 ``PROCS`` 个进程跑同一段脚本，全部跑完才返回。"""
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, target, f"p{n}", str(ENTRIES_PER_PROC)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for n in range(PROCS)
    ]
    failures = []
    for proc in procs:
        _out, err = proc.communicate(timeout=180)
        if proc.returncode != 0:
            failures.append(err.decode("utf-8", "replace"))
    assert not failures, "子进程写入失败:\n" + "\n".join(failures)


class TestConcurrentJournalWrites:
    def test_no_lost_updates(self, tmp_path):
        """4 进程各写 15 条 → 必须落盘 60 条（无锁时只剩约 15 条）。"""
        journal_file = str(tmp_path / "journal.json")
        _run_parallel(_JOURNAL_WRITER, journal_file)

        with open(journal_file, encoding="utf-8") as f:
            journal = json.load(f)

        names = {e["items"][0]["name"] for e in journal}
        assert len(journal) == EXPECTED, f"并发写入丢了 {EXPECTED - len(journal)} 条"
        assert len(names) == EXPECTED, "条目被覆盖：条数够但名字重复"

    def test_lock_file_is_separate_from_data_file(self, tmp_path):
        """锁必须落在独立文件上：数据文件每次 ``os.replace`` 都换 inode。"""
        journal_file = str(tmp_path / "journal.json")
        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.JOURNAL_FILE = journal_file
        adapter._JOURNAL_MAX_ENTRIES = 100

        adapter._log_to_local_journal("2026-01-01", "Lunch", [{"name": "Apple", "calories": 95}])

        assert os.path.exists(journal_file + ".lock")
        # 数据文件本身没有被锁文件占用（内容仍是合法 JSON）
        with open(journal_file, encoding="utf-8") as f:
            assert isinstance(json.load(f), list)


class TestConcurrentFoodCacheWrites:
    def test_no_lost_updates(self, tmp_path):
        """4 进程各写 15 个缓存条目 → 必须全部保留（无锁时只剩约 15 个）。"""
        cache_file = str(tmp_path / "food_cache.json")
        _run_parallel(_CACHE_WRITER, cache_file)

        with open(cache_file, encoding="utf-8") as f:
            entries = json.load(f)["entries"]

        assert len(entries) == EXPECTED, f"缓存并发写入丢了 {EXPECTED - len(entries)} 个条目"


class TestFileLockDegradation:
    """锁机制本身出问题时，绝不能把调用方的写入一起挡掉。"""

    def test_timeout_still_enters_critical_section(self, tmp_path):
        """锁被别的进程占住且超时 → 告警后继续执行，不无限阻塞。"""
        lock_path = str(tmp_path / "journal.json.lock")
        entered = False
        with open(lock_path, "a+", encoding="utf-8") as holder:
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
            started = time.monotonic()
            with _file_lock(lock_path, timeout=0.05):
                entered = True
            elapsed = time.monotonic() - started

        assert entered is True
        assert elapsed >= 0.05, "应该等满超时才放弃，说明根本没尝试加锁"
        assert elapsed < 5.0, "超时后必须立即放弃，不能退化成无限等待"

    def test_uncreatable_lock_file_degrades(self, tmp_path):
        """锁文件建不出来（父路径是普通文件）→ 不加锁继续，而不是抛异常。"""
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("x", encoding="utf-8")
        entered = False

        with _file_lock(str(blocker / "journal.json.lock"), timeout=0.05):
            entered = True

        assert entered is True

    def test_lock_is_released_after_exception(self, tmp_path):
        """临界区里抛异常也必须解锁，否则后续写入会一直等到超时。"""
        lock_path = str(tmp_path / "journal.json.lock")
        try:
            with _file_lock(lock_path, timeout=0.05):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        started = time.monotonic()
        with _file_lock(lock_path, timeout=5.0):
            pass
        assert time.monotonic() - started < 1.0, "锁没释放，第二次进入被阻塞"


class TestRemoveKeepsConcurrentWrites:
    def test_remove_does_not_drop_unrelated_entries(self, tmp_path):
        """删除一条时不能把 journal 里其他条目一起抹掉。"""
        journal_file = str(tmp_path / "journal.json")
        adapter = MFPAdapter.__new__(MFPAdapter)
        adapter.JOURNAL_FILE = journal_file
        adapter._JOURNAL_MAX_ENTRIES = 100

        adapter._log_to_local_journal(
            "2026-01-01", "Lunch",
            [{"name": "Apple", "calories": 95}, {"name": "Rice", "calories": 200}],
        )
        adapter._log_to_local_journal("2026-01-01", "Dinner", [{"name": "Egg", "calories": 90}])

        assert adapter._remove_from_journal("2026-01-01", "Lunch", "Apple") == 1

        with open(journal_file, encoding="utf-8") as f:
            journal = json.load(f)
        assert [e["meal_name"] for e in journal] == ["Lunch", "Dinner"]
        assert [i["name"] for i in journal[0]["items"]] == ["Rice"]
