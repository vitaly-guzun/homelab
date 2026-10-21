"""Importer edge cases; integration checks are documented in README.md."""
import copy
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import import_whoop as importer


def fixture(folder):
    common = {"Cycle start time": "2026-06-04 00:30:00", "Cycle end time": "",
              "Cycle timezone": "UTC-04:00"}
    cycles = {**common, **dict.fromkeys(importer.CYCLE_NUMBERS.values(), "")}
    cycles["Recovery score %"] = "0"
    sleeps = {**common, **dict.fromkeys(importer.SLEEP_NUMBERS.values(), ""),
              "Sleep onset": "2026-06-04 00:30:00", "Wake onset": "2026-06-04 07:30:00", "Nap": "false"}
    workouts = {**common, **dict.fromkeys(importer.WORKOUT_NUMBERS.values(), ""),
                "Workout start time": "2026-06-04 10:00:00", "Workout end time": "2026-06-04 11:00:00",
                "Activity name": "Runner's workout", "GPS enabled": "false"}
    rows = {"physiological_cycles.csv": [cycles], "sleeps.csv": [sleeps], "workouts.csv": [workouts]}
    write_fixture(folder, rows)
    return rows


def write_fixture(folder, tables):
    for filename, rows in tables.items():
        with (folder / filename).open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.rows = fixture(self.folder)

    def test_offsets_zeros_blanks_and_original_local_time(self):
        data = importer.load_export(self.folder)
        self.assertEqual(data["cycles"][0]["cycle_start"], datetime(2026, 6, 4, 4, 30, tzinfo=timezone.utc))
        self.assertEqual(data["cycles"][0]["recovery"], Decimal(0))
        self.assertIsNone(data["cycles"][0]["day_strain"])
        self.assertEqual(data["sleeps"][0]["local_end"], "2026-06-04 07:30:00")
        self.assertFalse(data["sleeps"][0]["nap"])

    def test_sql_is_transactional_and_escapes_activity(self):
        sql = importer.render_sql(importer.load_export(self.folder))
        self.assertIn("'Runner''s workout'", sql)
        self.assertEqual(sql.count("ON CONFLICT"), 3)
        self.assertIn("BEGIN;", sql)
        self.assertTrue(sql.endswith("COMMIT;\n"))

    def test_duplicate_session_rejected(self):
        self.rows["workouts.csv"] *= 2
        write_fixture(self.folder, self.rows)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            importer.load_export(self.folder)

    def test_missing_cycle_rejected(self):
        self.rows["workouts.csv"][0]["Cycle start time"] = "2026-06-03 00:30:00"
        write_fixture(self.folder, self.rows)
        with self.assertRaisesRegex(ValueError, "cycle reference missing"):
            importer.load_export(self.folder)

    def test_invalid_number_and_percentage_rejected(self):
        for value in ("NaN", "Infinity", "oops", "-1", "101"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    importer.number(value, "HR Zone 1 %")

    def test_multiple_main_sleeps_rejected_but_naps_allowed(self):
        second = copy.deepcopy(self.rows["sleeps.csv"][0])
        second.update({"Sleep onset": "2026-06-04 13:00:00", "Wake onset": "2026-06-04 14:00:00"})
        self.rows["sleeps.csv"].append(second)
        write_fixture(self.folder, self.rows)
        with self.assertRaisesRegex(ValueError, "multiple main sleeps"):
            importer.load_export(self.folder)
        second["Nap"] = "true"
        write_fixture(self.folder, self.rows)
        self.assertEqual(len(importer.load_export(self.folder)["sleeps"]), 2)

    def test_timezone_and_boolean_validation(self):
        for value in ("Europe/Amsterdam", "UTC+15:00", "UTC+14:30", "UTC+02:99"):
            with self.assertRaises(ValueError):
                importer.offset(value)
        with self.assertRaises(ValueError):
            importer.boolean("yes")


if __name__ == "__main__":
    unittest.main()
