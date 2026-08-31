import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "fetch_data.py"
SPEC = importlib.util.spec_from_file_location("fetch_data", MODULE_PATH)
fetch_data = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_data
SPEC.loader.exec_module(fetch_data)


class FuturesUpdateTests(unittest.TestCase):
    TEST_DATE = "2026-08-28"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.now = datetime(2026, 8, 31, 16, 0, tzinfo=fetch_data.TPE)

        patchers = (
            mock.patch.object(fetch_data, "DATA_DIR", self.temp_dir.name),
            mock.patch.object(fetch_data, "NOW", self.now),
            mock.patch.object(fetch_data, "TODAY", "2026-08-31"),
            mock.patch.object(fetch_data, "FORCE", False),
            mock.patch.object(fetch_data.time, "sleep", return_value=None),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _roles(self, *, all_zero=False):
        if all_zero:
            return {
                "外資及陸資": {"l": 0, "s": 0},
                "投信": {"l": 0, "s": 0},
                "自營商": {"l": 0, "s": 0},
            }
        return {
            "外資及陸資": {"l": 200, "s": 150},
            "投信": {"l": 0, "s": 0},
            "自營商": {"l": 50, "s": 60},
        }

    def _institutional_day(self, *, all_zero=False, codes=None):
        selected = codes or tuple(fetch_data.PRODUCTS)
        return {
            self.TEST_DATE: {
                fetch_data.PRODUCTS[code]["name"]: self._roles(all_zero=all_zero)
                for code in selected
            }
        }

    def _market_fetch(self, totals=None):
        totals = totals or {code: {self.TEST_DATE: 1_000} for code in fetch_data.PRODUCTS}

        def fetch(code, start, end):
            return totals[code]

        return fetch

    def _row(self, date_string, *, provisional=False):
        roles = self._roles(all_zero=provisional)
        simplified = {
            "外資": {
                "l": roles["外資及陸資"]["l"],
                "s": roles["外資及陸資"]["s"],
                "net": roles["外資及陸資"]["l"] - roles["外資及陸資"]["s"],
            },
            "投信": {
                "l": roles["投信"]["l"],
                "s": roles["投信"]["s"],
                "net": roles["投信"]["l"] - roles["投信"]["s"],
            },
            "自營商": {
                "l": roles["自營商"]["l"],
                "s": roles["自營商"]["s"],
                "net": roles["自營商"]["l"] - roles["自營商"]["s"],
            },
        }
        inst_l = sum(role["l"] for role in simplified.values())
        inst_s = sum(role["s"] for role in simplified.values())
        retail_l = 1_000 - inst_l
        retail_s = 1_000 - inst_s
        return {
            "date": date_string,
            "total": 1_000,
            "inst": simplified,
            "retail": {
                "l": retail_l,
                "s": retail_s,
                "net": retail_l - retail_s,
                "ratio": round((retail_l - retail_s) / 1_000 * 100, 2),
            },
        }

    def _write_futures(self, history):
        path = Path(self.temp_dir.name) / "futures.json"
        path.write_text(
            json.dumps({"updated": "", "history": history}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read_futures(self):
        path = Path(self.temp_dir.name) / "futures.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_all_products_all_roles_zero_with_positive_total_is_not_persisted(self):
        with (
            mock.patch.object(
                fetch_data,
                "fetch_latest_ready_institutional",
                return_value=(
                    self._institutional_day(all_zero=True),
                    date.fromisoformat(self.TEST_DATE),
                ),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
        ):
            changed = fetch_data.update_futures()

        self.assertFalse(changed)
        self.assertFalse((Path(self.temp_dir.name) / "futures.json").exists())

    def test_existing_poisoned_row_is_removed_while_source_is_still_provisional(self):
        self._write_futures(
            {
                code: [self._row(self.TEST_DATE, provisional=True)]
                for code in fetch_data.PRODUCTS
            }
        )
        with (
            mock.patch.object(
                fetch_data,
                "fetch_latest_ready_institutional",
                return_value=(
                    self._institutional_day(all_zero=True),
                    date.fromisoformat(self.TEST_DATE),
                ),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
        ):
            changed = fetch_data.update_futures()

        self.assertTrue(changed)
        saved = self._read_futures()
        for code in fetch_data.PRODUCTS:
            self.assertEqual([], saved["history"][code])

    def test_single_role_zero_is_valid_when_other_roles_have_open_interest(self):
        with (
            mock.patch.object(
                fetch_data,
                "fetch_taifex_institutional",
                return_value=self._institutional_day(),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
        ):
            changed = fetch_data.update_futures()

        self.assertTrue(changed)
        saved = self._read_futures()
        for code in fetch_data.PRODUCTS:
            self.assertEqual([self.TEST_DATE], [row["date"] for row in saved["history"][code]])
        self.assertEqual(
            {"l": 0, "s": 0, "net": 0},
            saved["history"]["TX"][0]["inst"]["投信"],
        )

    def test_final_row_replaces_same_date_provisional_row_without_duplicate(self):
        self._write_futures(
            {
                code: [self._row(self.TEST_DATE, provisional=True)]
                for code in fetch_data.PRODUCTS
            }
        )
        with (
            mock.patch.object(fetch_data, "TODAY", self.TEST_DATE),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_institutional",
                return_value=self._institutional_day(),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
        ):
            changed = fetch_data.update_futures()

        self.assertTrue(changed)
        saved = self._read_futures()
        for code in fetch_data.PRODUCTS:
            rows = saved["history"][code]
            self.assertEqual(1, len([row for row in rows if row["date"] == self.TEST_DATE]))
            final = next(row for row in rows if row["date"] == self.TEST_DATE)
            self.assertEqual({"l": 200, "s": 150, "net": 50}, final["inst"]["外資"])

    def test_identical_overlap_data_does_not_write_again(self):
        self._write_futures(
            {
                code: [self._row(self.TEST_DATE)]
                for code in fetch_data.PRODUCTS
            }
        )
        with (
            mock.patch.object(
                fetch_data,
                "fetch_taifex_institutional",
                return_value=self._institutional_day(),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
            mock.patch.object(fetch_data, "save_json") as save,
        ):
            changed = fetch_data.update_futures()

        self.assertFalse(changed)
        save.assert_not_called()

    def test_before_1510_never_queries_unpublished_current_date(self):
        monday_before_publish = datetime(2026, 8, 31, 14, 46, tzinfo=fetch_data.TPE)
        institutional = mock.Mock(return_value=self._institutional_day())
        with (
            mock.patch.object(fetch_data, "NOW", monday_before_publish),
            mock.patch.object(fetch_data, "fetch_taifex_institutional", institutional),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
        ):
            fetch_data.update_futures()

        for call in institutional.call_args_list:
            self.assertLessEqual(call.args[1], date(2026, 8, 30))

    def test_overlap_start_includes_each_products_three_most_recent_rows(self):
        dates_by_code = {
            "TX": ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"],
            "MTX": ["2026-08-22", "2026-08-25", "2026-08-28"],
            "TMF": ["2026-08-24", "2026-08-27", "2026-08-28"],
        }
        self._write_futures(
            {
                code: [self._row(date_string) for date_string in dates]
                for code, dates in dates_by_code.items()
            }
        )
        institutional = mock.Mock(return_value=self._institutional_day())
        market = mock.Mock(side_effect=self._market_fetch())

        with (
            mock.patch.object(fetch_data, "fetch_taifex_institutional", institutional),
            mock.patch.object(fetch_data, "fetch_taifex_market_oi", market),
        ):
            fetch_data.update_futures()

        institutional_start = institutional.call_args.args[0]
        oldest_required = min(
            date.fromisoformat(sorted(dates)[-3]) for dates in dates_by_code.values()
        )
        self.assertLessEqual(institutional_start, oldest_required)

        calls_by_code = {call.args[0]: call.args[1] for call in market.call_args_list}
        self.assertEqual(set(fetch_data.PRODUCTS), set(calls_by_code))
        for code, dates in dates_by_code.items():
            third_most_recent = date.fromisoformat(sorted(dates)[-3])
            self.assertLessEqual(calls_by_code[code], third_most_recent)

    def test_date_missing_one_product_does_not_partially_persist_other_products(self):
        incomplete = self._institutional_day(codes=("TX", "MTX"))
        with (
            mock.patch.object(
                fetch_data,
                "fetch_latest_ready_institutional",
                return_value=(incomplete, date.fromisoformat(self.TEST_DATE)),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(),
            ),
        ):
            changed = fetch_data.update_futures()

        self.assertFalse(changed)
        self.assertFalse((Path(self.temp_dir.name) / "futures.json").exists())

    def test_no_ready_institutional_day_raises_instead_of_succeeding_silently(self):
        with mock.patch.object(
            fetch_data,
            "fetch_latest_ready_institutional",
            return_value=({}, None),
        ):
            with self.assertRaisesRegex(RuntimeError, "無可驗證資料"):
                fetch_data.update_futures()

    def test_latest_market_oi_missing_raises_instead_of_succeeding_silently(self):
        totals = {
            code: {self.TEST_DATE: 1_000}
            for code in fetch_data.PRODUCTS
        }
        totals["TMF"] = {}
        with (
            mock.patch.object(
                fetch_data,
                "fetch_latest_ready_institutional",
                return_value=(
                    self._institutional_day(),
                    date.fromisoformat(self.TEST_DATE),
                ),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(totals),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "全市場 OI 無可驗證資料: TMF"):
                fetch_data.update_futures()

    def test_institutional_total_above_market_oi_rejects_entire_day(self):
        totals = {
            code: {self.TEST_DATE: 1_000}
            for code in fetch_data.PRODUCTS
        }
        totals["MTX"][self.TEST_DATE] = 100
        with (
            mock.patch.object(
                fetch_data,
                "fetch_latest_ready_institutional",
                return_value=(
                    self._institutional_day(),
                    date.fromisoformat(self.TEST_DATE),
                ),
            ),
            mock.patch.object(
                fetch_data,
                "fetch_taifex_market_oi",
                side_effect=self._market_fetch(totals),
            ),
        ):
            changed = fetch_data.update_futures()

        self.assertFalse(changed)
        self.assertFalse((Path(self.temp_dir.name) / "futures.json").exists())


class MainTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir_patcher = mock.patch.object(fetch_data, "DATA_DIR", self.temp_dir.name)
        self.data_dir_patcher.start()
        self.addCleanup(self.data_dir_patcher.stop)

    def _patch_updaters(self, *, futures_side_effect=None):
        stack = ExitStack()
        mocks = {
            "update_futures": stack.enter_context(
                mock.patch.object(
                    fetch_data,
                    "update_futures",
                    side_effect=futures_side_effect,
                    return_value=False,
                )
            )
        }
        for name in (
            "update_options",
            "update_margin",
            "update_taiex_tsmc",
            "update_top10_ssf",
        ):
            mocks[name] = stack.enter_context(
                mock.patch.object(fetch_data, name, return_value=False)
            )
        return stack, mocks

    def test_weekend_delayed_run_still_calls_all_updaters(self):
        saturday = datetime(2026, 8, 29, 16, 0, tzinfo=fetch_data.TPE)
        stack, updaters = self._patch_updaters()
        with (
            stack,
            mock.patch.object(fetch_data, "NOW", saturday),
            mock.patch.object(fetch_data, "TODAY", "2026-08-29"),
            mock.patch.object(fetch_data, "FORCE", False),
        ):
            fetch_data.main()

        for updater in updaters.values():
            updater.assert_called_once_with()

    def test_updater_exception_makes_main_raise(self):
        stack, updaters = self._patch_updaters(futures_side_effect=RuntimeError("boom"))
        monday = datetime(2026, 8, 31, 16, 0, tzinfo=fetch_data.TPE)

        with stack, mock.patch.object(fetch_data, "NOW", monday), mock.patch.object(
            fetch_data, "FORCE", False
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                fetch_data.main()

        for updater in updaters.values():
            updater.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
