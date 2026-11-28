"""The active Hermes baseline must preserve the current dashboard profit contract."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
RUNTIME = ROOT / "releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/business-baseline.md"
CANONICAL = ROOT / "docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md"

class CurrentDashboardBaselineTest(unittest.TestCase):
    def test_actual_coins_reader_recognizes_active_baseline_identity(self):
        reader = ROOT / "releases/fs-dashboard/fc-coins-evidence-20261021/source/coins_evidence.py"
        spec = importlib.util.spec_from_file_location("active_coins_evidence", reader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.__file__ = str(RUNTIME.with_name("coins_evidence.py"))
        self.assertEqual(module.baseline_identity(), {
            "version": "business-baseline-fc-v6-20261128",
            "sha256": hashlib.sha256(RUNTIME.read_bytes()).hexdigest(),
        })

    def test_runtime_uses_shipping_and_provenance_tracks_published_bytes(self):
        runtime = RUNTIME.read_bytes().replace(b"\r\n", b"\n")
        canonical = CANONICAL.read_bytes().replace(b"\r\n", b"\n")
        text = runtime.decode("utf-8")
        for stale in ("dashboard-actual-profit-current-20261024", "看板自动读取使用原鉴权channel-effects入口mode=actual-profit", "发货统计的利润及利润率从看板隐藏", "经营分析看板实际成本毛利主展示保持独立", "毛利仍是同网站同批付款订单逐单实际成本"):
            self.assertNotIn(stale, text)
        self.assertIn("毛利（¥）=同一响应的人民币销售总额−采购总额", text)
        self.assertIn("标为预估非实结", text)
        self.assertIn("逐单实际采购成本独立核算", text)
        self.assertIn("原逐单核算接口、归档与Hermes按需查询能力保留", text)
        for entry in (
            "北京时间每小时 15 分到期，零点亦为 00:15",
            "昨日 ES 未就绪时沿原任务续跑",
            "D-3 至 D-1",
            "`business.fc_project_review`",
            "`profile,start,end,view=same-order`",
            "今天的付款汇总用原 `business.summary`",
            "/dashboard/analytics/campaigns/analytics/products.html",
            "周更只选品和保存草稿",
        ):
            self.assertIn(entry, text)
        package_rule = next(line for line in canonical.decode("utf-8").splitlines()
                            if line.startswith("`fc27_curve_v6` 按 PS、Xbox、PC 各自全球统一价"))
        self.assertIn("U4GM 仅作观察", package_rule)
        self.assertIn("缺领取或回执时，尝试或结果待核", package_rule)
        self.assertIn(package_rule, text.splitlines())
        provenance = json.loads(RUNTIME.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["canonical_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(provenance["after_sha256"], hashlib.sha256(runtime).hexdigest())
        self.assertEqual(provenance["bytes"], len(runtime))

if __name__ == "__main__":
    unittest.main()
