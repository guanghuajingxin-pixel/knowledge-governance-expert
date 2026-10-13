import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routes import metrics_route


class MetricsOverviewTests(unittest.IsolatedAsyncioTestCase):
    def _session_with_row(self, **values):
        """构造只返回一行、含 4 个计数列的假会话（对应合并后的单条 SQL）。"""
        row = SimpleNamespace(**values)
        return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(one=lambda: row)))

    async def test_overview_aggregates_real_counts(self):
        # 一条 SQL 的 4 个标量子查询：本地上传 / 同步采集 / 累计采纳 / 累计反馈
        session = self._session_with_row(upload_new=2, sync_new=3, adopted=5, feedback=9)
        data = await metrics_route.metrics_overview(u=SimpleNamespace(id=1), s=session)
        self.assertEqual(data["today_new"], 5)  # 2 + 3
        self.assertEqual(data["total_adopted"], 5)
        self.assertEqual(data["total_feedback"], 9)
        # 合并后只应有一次数据库往返（原先多次串行，首屏要等多个来回）
        self.assertEqual(session.execute.await_count, 1)

    async def test_overview_empty_database_returns_zeros(self):
        session = self._session_with_row(upload_new=None, sync_new=None,
                                        adopted=None, feedback=None)
        data = await metrics_route.metrics_overview(u=SimpleNamespace(id=1), s=session)
        self.assertEqual(data, {
            "today_new": 0,
            "total_adopted": 0,
            "total_feedback": 0,
        })

    def test_overview_route_is_registered(self):
        from app.main import app
        self.assertIn("/api/v1/metrics/overview", app.openapi()["paths"])


    def test_day_start_is_user_timezone_midnight_in_naive_utc(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        cutoff = metrics_route._day_start()
        self.assertIsNone(cutoff.tzinfo)
        now_cst = datetime.now(ZoneInfo("Asia/Shanghai"))
        expected = (now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(hours=8))
        self.assertEqual(cutoff, expected.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
