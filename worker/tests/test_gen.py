import json
import tempfile
import unittest
from pathlib import Path

from kclog import gen, prompts
from kclog.collect import write_json
from kclog.track import load_track

ROOT = Path(__file__).resolve().parents[2]


def make_commit(sha, subject, files, vendor=None):
    return {
        "sha": sha, "release": "v6.3", "author": {"name": "A", "email": "a@x"},
        "author_date": "2023-01-01T00:00:00+00:00", "commit_date": "2023-01-02T00:00:00+00:00",
        "subject": subject, "body": "body\n\nSigned-off-by: A <a@x>",
        "fixes": [], "cc_stable": False, "files": files, "area": "core",
        "vendor": vendor, "vendors": [vendor] if vendor else [],
        "patch": f"patches/{sha[:12]}.diff", "summary_ko": None, "explanation_ko": None,
    }


def track_file(path, added=1, deleted=0):
    return {"path": path, "status": "M", "in_track": True, "added": added, "deleted": deleted}


def other_file(path):
    return {"path": path, "status": "M", "in_track": False}


COMMIT_OUT = {"summary_ko": "요약", "change_type": "fix", "importance": "high",
              "explanation_ko": "### 배경\n...", "keywords": ["MCQ"]}


class ValidateTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(gen.validate(prompts.COMMIT_SCHEMA, COMMIT_OUT), [])

    def test_errors(self):
        bad = dict(COMMIT_OUT, change_type="bugfix", extra=1)
        del bad["keywords"]
        errors = gen.validate(prompts.COMMIT_SCHEMA, bad)
        self.assertTrue(any("keywords: 누락" in e for e in errors))
        self.assertTrue(any("extra: 허용되지 않은" in e for e in errors))
        self.assertTrue(any("change_type" in e for e in errors))

    def test_nested(self):
        out = {"headline_ko": "h", "area_notes": [{"area": "core"}],
               "highlights": [{"title_ko": "t", "description_ko": "d", "commits": [1]}]}
        errors = gen.validate(prompts.RELEASE_SCHEMA, out)
        self.assertIn("$.highlights[0].commits[0]: string이 아님", errors)
        self.assertIn("$.area_notes[0].summary_ko: 누락", errors)


class GenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.work = Path(self.tmp.name) / "work"
        rel = self.data_dir / "v6.3"
        commits = [
            make_commit("a" * 40, "scsi: ufs: core: fix A",
                        [track_file("drivers/ufs/core/ufshcd.c", 10, 2)]),
            make_commit("b" * 40, "scsi: ufs: qcom: B",
                        [track_file("drivers/ufs/host/ufs-qcom.c")], vendor="qcom"),
            make_commit("c" * 40, "treewide: C",
                        [track_file("drivers/ufs/core/ufshcd.c")]
                        + [other_file(f"drivers/x{i}.c") for i in range(3)]),
        ]
        series = [
            {"id": "s1", "title": "fix A", "commits": ["a" * 40, "b" * 40], "areas": ["core", "host"]},
            {"id": "s2", "title": "C", "commits": ["c" * 40], "areas": ["core"]},
        ]
        write_json(rel / "commits.json", commits)
        write_json(rel / "series.json", series)
        (rel / "patches").mkdir()
        for c in commits:
            (rel / c["patch"]).write_text("diff --git a/x b/x\n+line\n", encoding="utf-8")
        self.track = load_track(ROOT / "tracks" / "ufs.toml")

    def tearDown(self):
        self.tmp.cleanup()

    def rd(self):
        return gen.ReleaseData(self.data_dir, "v6.3")

    def write_result(self, job_id, out):
        (self.work / f"{job_id}.json").write_text(json.dumps(out, ensure_ascii=False), "utf-8")

    def test_explain_policy(self):
        a, b, c = self.rd().commits
        self.assertTrue(gen.should_explain(self.track, a))
        self.assertTrue(gen.is_treewide(c))
        self.assertFalse(gen.should_explain(self.track, c))
        self.track.policy.setdefault("vendors", {})["qcom"] = {"explain": False}
        self.assertFalse(gen.should_explain(self.track, b))

    def test_commit_input(self):
        jobs = gen.commit_jobs(self.rd(), self.track, force=False)
        self.assertEqual(len(jobs), 3)
        self.assertIn("mode: full", jobs[0].user)
        self.assertIn("series: 2개 패치", jobs[0].user)
        self.assertIn("mode: summary-only", jobs[2].user)
        self.assertIn("UFS 밖 파일 3개", jobs[2].user)
        self.assertIn("<diff>\ndiff --git", jobs[0].user)

    def test_export_import_roundtrip(self):
        rd = self.rd()
        jobs = gen.commit_jobs(rd, self.track, force=False)
        gen.export_jobs("commits", jobs, self.work)
        self.assertIn("summary_ko", (self.work / "INSTRUCTIONS.md").read_text("utf-8"))
        self.assertEqual(len(list(self.work.glob("*.input.md"))), 3)

        self.write_result("c-" + "a" * 40, COMMIT_OUT)
        self.write_result("c-" + "c" * 40, COMMIT_OUT)
        self.write_result("c-" + "b" * 40, dict(COMMIT_OUT, importance="urgent"))
        (self.work / "c-unknown.json").write_text("{}", "utf-8")

        applied, failures = gen.import_results("commits", jobs, self.work, "claude-opus-5-5")
        self.assertEqual(len(applied), 2)
        self.assertEqual(sorted(f[0] for f in failures), ["c-" + "b" * 40, "c-unknown"])
        a, b, c = rd.commits
        self.assertEqual(a["summary_ko"], "요약")
        self.assertEqual(a["gen"]["model"], "claude-opus-5-5")
        self.assertEqual(a["gen"]["prompt_version"], prompts.PROMPT_VERSION)
        self.assertIsNone(b["summary_ko"])
        self.assertIsNone(c["explanation_ko"])  # 트리 전반 변경은 요약만
        # 저장 후 반영된 항목의 작업 파일만 지우고, 실패한 항목은 남긴다
        self.assertTrue((self.work / f"c-{'a' * 40}.json").exists())
        gen.remove_work_files(self.work, applied)
        self.assertFalse((self.work / f"c-{'a' * 40}.input.md").exists())
        self.assertFalse((self.work / f"c-{'a' * 40}.json").exists())
        self.assertTrue((self.work / f"c-{'b' * 40}.json").exists())
        # 이미 생성된 항목은 다음 export에서 빠진다
        self.assertEqual(len(gen.commit_jobs(rd, self.track, force=False)), 1)

    def test_batch_file(self):
        rd = self.rd()
        jobs = gen.commit_jobs(rd, self.track, force=False)
        gen.export_jobs("commits", jobs, self.work)
        batch = {"c-" + "a" * 40: COMMIT_OUT, "c-" + "b" * 40: {"summary_ko": "x"}}
        (self.work / "batch-1.json").write_text(json.dumps(batch, ensure_ascii=False), "utf-8")
        applied, failures = gen.import_results("commits", jobs, self.work, None)
        self.assertEqual(applied, ["c-" + "a" * 40])
        self.assertEqual([f[0] for f in failures], ["c-" + "b" * 40])
        gen.remove_work_files(self.work, applied)
        # 실패한 항목만 batch 파일에 남는다
        rest = json.loads((self.work / "batch-1.json").read_text("utf-8"))
        self.assertEqual(list(rest), ["c-" + "b" * 40])

    def test_series_and_release(self):
        rd = self.rd()
        for job in gen.commit_jobs(rd, self.track, force=False):
            job.apply(COMMIT_OUT, gen.gen_info(None))

        sjobs = gen.series_jobs(rd, force=False)
        self.assertEqual(len(sjobs), 1)  # 다중 커밋 시리즈만 작업이 된다
        self.assertEqual(rd.series[1]["summary_ko"], "요약")
        sjobs[0].apply({"title_ko": "제목", "summary_ko": "시리즈 요약"}, gen.gen_info(None))

        release = {"tag": "v6.3", "prev_tag": "v6.2", "commit_count": 3}
        [rjob] = gen.release_jobs(rd, release, force=False)
        self.assertIn("aaaaaaaaaaaa bbbbbbbbbbbb", rjob.user)
        rjob.apply({"headline_ko": "h", "area_notes": [],
                    "highlights": [{"title_ko": "t", "description_ko": "d",
                                    "commits": ["aaaaaaaaaaaa", "deadbeef0000"]}]},
                   gen.gen_info(None))
        self.assertEqual(release["highlights_ko"]["highlights"][0]["commits"], ["aaaaaaaaaaaa"])

    def test_series_id_scoped_by_release(self):
        # 같은 송신 묶음(시리즈 키)이 두 릴리스에 나뉘어 들어간 경우
        rd = self.rd()
        other = self.data_dir / "v6.4"
        write_json(other / "commits.json", rd.commits)
        write_json(other / "series.json", rd.series)
        rd2 = gen.ReleaseData(self.data_dir, "v6.4")
        for r in (rd, rd2):
            for c in r.commits:
                c.update(COMMIT_OUT)
        [j1], [j2] = gen.series_jobs(rd, force=False), gen.series_jobs(rd2, force=False)
        self.assertNotEqual(j1.id, j2.id)
        with self.assertRaises(ValueError):
            gen.import_results("series", [j1, j1], self.work, None)


if __name__ == "__main__":
    unittest.main()
