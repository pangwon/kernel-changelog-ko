import unittest
from pathlib import Path

from kclog.gitrepo import parse_log, split_by_commit, version_key
from kclog.series import message_id, series_key
from kclog.track import load_track
from kclog.trailers import is_cc_stable, parse_fixes, parse_trailers

ROOT = Path(__file__).resolve().parents[2]


class TrackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.track = load_track(ROOT / "tracks" / "ufs.toml")

    def test_in_track(self):
        t = self.track
        self.assertTrue(t.in_track("drivers/ufs/core/ufshcd.c"))
        self.assertTrue(t.in_track("drivers/phy/qualcomm/phy-qcom-qmp-ufs.c"))
        self.assertTrue(t.in_track("drivers/soc/qcom/ice.c"))
        self.assertFalse(t.in_track("drivers/phy/qualcomm/phy-qcom-qmp-usb.c"))
        self.assertFalse(t.in_track("fs/ufs/super.c"))
        self.assertFalse(t.in_track("drivers/ufsx/foo.c"))

    def test_area(self):
        t = self.track
        self.assertEqual(t.area_of("drivers/ufs/host/ufs-qcom.c"), "host")
        self.assertEqual(t.area_of("drivers/ufs/core/ufshcd.c"), "core")
        self.assertEqual(t.area_of("drivers/ufs/Kconfig"), "core")
        self.assertEqual(t.area_of("include/ufs/ufshcd.h"), "core")
        self.assertEqual(t.area_of("Documentation/devicetree/bindings/ufs/qcom,ufs.yaml"), "bindings")
        self.assertEqual(t.area_of("Documentation/ABI/testing/sysfs-driver-ufs"), "docs")
        self.assertEqual(t.area_of("drivers/phy/samsung/phy-samsung-ufs.c"), "phy")
        self.assertEqual(t.area_of("drivers/soc/qcom/ice.c"), "crypto")

    def test_vendor(self):
        t = self.track
        self.assertEqual(t.vendor_of("drivers/ufs/host/ufs-qcom.c"), "qcom")
        self.assertEqual(t.vendor_of("drivers/ufs/host/ufs-exynos.c"), "exynos")
        self.assertEqual(t.vendor_of("drivers/ufs/host/ufs-mediatek-trace.h"), "mediatek")
        self.assertEqual(t.vendor_of("drivers/ufs/host/ufshcd-pci.c"), "intel")
        self.assertEqual(t.vendor_of("drivers/ufs/host/tc-dwc-g210-pci.c"), "snps")
        self.assertEqual(t.vendor_of("Documentation/devicetree/bindings/ufs/samsung,exynos-ufs.yaml"), "exynos")
        self.assertEqual(t.vendor_of("drivers/phy/qualcomm/phy-qcom-qmp-ufs.c"), "qcom")
        self.assertEqual(t.vendor_of("drivers/soc/qcom/ice.c"), "qcom")
        self.assertIsNone(t.vendor_of("drivers/ufs/core/ufshcd.c"))
        self.assertIsNone(t.vendor_of("drivers/ufs/host/Kconfig"))
        self.assertIsNone(t.vendor_of("Documentation/devicetree/bindings/ufs/ufs-common.yaml"))


class TrailerTest(unittest.TestCase):
    TEXT = (
        "Fixes: 0123456789ab (\"scsi: ufs: core: Fix foo\")\n"
        "Cc: stable@vger.kernel.org # 6.1+\n"
        "Signed-off-by: A <a@example.com>\n"
        "Link: https://lore.kernel.org/r/20240901123456.4242-3-a@example.com\n"
        "Reviewed-by: B <b@example.com>\n"
        "Signed-off-by: Martin K. Petersen <martin.petersen@oracle.com>\n"
    )

    def test_parse(self):
        t = parse_trailers(self.TEXT)
        self.assertEqual(len(t["signed_off_by"]), 2)
        self.assertEqual(t["reviewed_by"], ["B <b@example.com>"])
        self.assertTrue(is_cc_stable(t))
        self.assertEqual(parse_fixes(t["fixes"]),
                         [{"abbrev": "0123456789ab", "subject": "scsi: ufs: core: Fix foo"}])

    def test_not_stable(self):
        self.assertFalse(is_cc_stable(parse_trailers("Cc: someone@kernel.org\n")))


class SeriesTest(unittest.TestCase):
    def test_message_id(self):
        self.assertEqual(
            message_id(["https://bugzilla.kernel.org/x",
                        "https://lore.kernel.org/r/20240901123456.4242-3-a@example.com"]),
            "20240901123456.4242-3-a@example.com")
        self.assertEqual(message_id(["https://patch.msgid.link/abc-1-def@x.org"]), "abc-1-def@x.org")
        self.assertEqual(message_id(["https://lore.kernel.org/linux-scsi/foo@bar.com/"]), "foo@bar.com")
        self.assertIsNone(message_id([]))

    def test_send_email_series(self):
        a = series_key("20240901123456.4242-2-a@example.com")
        b = series_key("20240901123456.4242-5-a@example.com")
        self.assertEqual(a[0], b[0])
        self.assertEqual((a[1], b[1]), (2, 5))

    def test_b4_series(self):
        a = series_key("20240513-ufs-clk-v2-1-0a1b2c3d4e5f@linaro.org")
        b = series_key("20240513-ufs-clk-v2-3-0a1b2c3d4e5f@linaro.org")
        self.assertEqual(a[0], b[0])
        self.assertEqual(b[1], 3)
        # 리비전이 다르면 다른 시리즈
        c = series_key("20240520-ufs-clk-v3-1-ffeeddccbbaa@linaro.org")
        self.assertNotEqual(a[0], c[0])

    def test_unknown_format(self):
        self.assertEqual(series_key("CAHk-abc@mail.gmail.com"), ("CAHk-abc@mail.gmail.com", None))


class GitParseTest(unittest.TestCase):
    def test_version_key(self):
        tags = ["v6.10", "v6.2", "v7.0", "v6.2-rc8", "v6.19", "v7.0-rc1"]
        self.assertEqual(sorted(tags, key=version_key),
                         ["v6.2-rc8", "v6.2", "v6.10", "v6.19", "v7.0-rc1", "v7.0"])

    def test_parse_log(self):
        oid1, oid2 = "a" * 40, "b" * 40
        out = (
            "\x1e" + "\x1f".join(["c" * 40, "A", "a@x", "2024-01-01T00:00:00+00:00",
                                  "2024-01-02T00:00:00+00:00", "scsi: ufs: subj",
                                  "body line\n\nSigned-off-by: A <a@x>\n",
                                  "Signed-off-by: A <a@x>\n"]) + "\x1f"
            f"\n\n:100644 100644 {oid1} {oid2} M\tdrivers/ufs/core/ufshcd.c\n"
            f":000000 100644 {'0' * 40} {oid2} A\tdrivers/ufs/host/ufs-new.c\n"
        )
        [c] = parse_log(out)
        self.assertEqual(c.subject, "scsi: ufs: subj")
        self.assertEqual([f.path for f in c.files],
                         ["drivers/ufs/core/ufshcd.c", "drivers/ufs/host/ufs-new.c"])
        self.assertEqual(c.files[1].status, "A")
        self.assertEqual(c.trailers, "Signed-off-by: A <a@x>")

    def test_split_by_commit(self):
        out = "\x1eaaa\n\n1\t2\tx.c\n\x1ebbb\n\n3\t4\ty.c\n"
        self.assertEqual(split_by_commit(out), {"aaa": "1\t2\tx.c", "bbb": "3\t4\ty.c"})


if __name__ == "__main__":
    unittest.main()
