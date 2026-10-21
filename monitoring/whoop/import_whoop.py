#!/usr/bin/env python3
"""Validate WHOOP CSVs; --apply imports via kubectl, --sql emits private SQL.

No dependencies or local credentials. Default mode only prints record counts.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import subprocess
import sys


CYCLE_NUMBERS = {
    "recovery": "Recovery score %", "resting_hr": "Resting heart rate (bpm)",
    "hrv_ms": "Heart rate variability (ms)", "skin_temp_c": "Skin temp (celsius)",
    "spo2": "Blood oxygen %", "day_strain": "Day Strain",
    "energy_cal": "Energy burned (cal)", "max_hr": "Max HR (bpm)",
    "average_hr": "Average HR (bpm)",
}
SLEEP_NUMBERS = {
    "performance": "Sleep performance %", "respiratory_rate": "Respiratory rate (rpm)",
    "asleep_min": "Asleep duration (min)", "in_bed_min": "In bed duration (min)",
    "light_min": "Light sleep duration (min)", "deep_min": "Deep (SWS) duration (min)",
    "rem_min": "REM duration (min)", "awake_min": "Awake duration (min)",
    "need_min": "Sleep need (min)", "debt_min": "Sleep debt (min)",
    "efficiency": "Sleep efficiency %", "consistency": "Sleep consistency %",
}
WORKOUT_NUMBERS = {
    "duration_min": "Duration (min)", "strain": "Activity Strain",
    "energy_cal": "Energy burned (cal)", "max_hr": "Max HR (bpm)",
    "average_hr": "Average HR (bpm)",
    **{f"zone{i}_pct": f"HR Zone {i} %" for i in range(1, 6)},
}


def offset(value):
    match = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", value)
    if not match or int(match[2]) > 14 or int(match[3]) > 59:
        raise ValueError("invalid Cycle timezone")
    minutes = int(match[2]) * 60 + int(match[3])
    if minutes > 14 * 60:
        raise ValueError("Cycle timezone is outside UTC offsets")
    return timezone(timedelta(minutes=minutes if match[1] == "+" else -minutes))


def instant(value, tz, required=True):
    if not value:
        if required:
            raise ValueError("missing required timestamp")
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).astimezone(timezone.utc)


def number(value, label):
    if not value:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value in {label}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite numeric value in {label}")
    if result < 0 or (label.endswith("%") and result > 100):
        raise ValueError(f"out-of-range numeric value in {label}")
    if label in ("Day Strain", "Activity Strain") and result > 21:
        raise ValueError(f"out-of-range numeric value in {label}")
    return result


def boolean(value):
    if value not in ("true", "false"):
        raise ValueError("expected true or false")
    return value == "true"


def read_csv(path, required):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not required.issubset(headers):
            raise ValueError(f"{path.name}: missing or duplicate headers")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name}: empty export")
    for line, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{path.name}:{line}: malformed CSV row")
    return rows


def load_export(folder):
    common = {"Cycle start time", "Cycle end time", "Cycle timezone"}
    specifications = [
        ("cycles", "physiological_cycles.csv", common | set(CYCLE_NUMBERS.values())),
        ("sleeps", "sleeps.csv", common | set(SLEEP_NUMBERS.values()) | {"Sleep onset", "Wake onset", "Nap"}),
        ("workouts", "workouts.csv", common | set(WORKOUT_NUMBERS.values()) | {
            "Workout start time", "Workout end time", "Activity name", "GPS enabled"}),
    ]
    result = {}
    for table, filename, required in specifications:
        records, seen = [], set()
        for line, row in enumerate(read_csv(folder / filename, required), 2):
            try:
                tz = offset(row["Cycle timezone"])
                item = {"cycle_start": instant(row["Cycle start time"], tz),
                        "timezone_offset": row["Cycle timezone"]}
                if table == "cycles":
                    item["cycle_end"] = instant(row["Cycle end time"], tz, required=False)
                    mapping, key = CYCLE_NUMBERS, "cycle_start"
                elif table == "sleeps":
                    item.update(sleep_start=instant(row["Sleep onset"], tz),
                                sleep_end=instant(row["Wake onset"], tz),
                                local_start=row["Sleep onset"], local_end=row["Wake onset"],
                                nap=boolean(row["Nap"]))
                    if item["sleep_end"] <= item["sleep_start"]:
                        raise ValueError("sleep end must follow sleep start")
                    mapping, key = SLEEP_NUMBERS, "sleep_start"
                else:
                    item.update(workout_start=instant(row["Workout start time"], tz),
                                workout_end=instant(row["Workout end time"], tz),
                                local_start=row["Workout start time"],
                                activity=row["Activity name"], gps_enabled=boolean(row["GPS enabled"]))
                    if not item["activity"] or item["workout_end"] <= item["workout_start"]:
                        raise ValueError("missing activity or invalid workout interval")
                    mapping, key = WORKOUT_NUMBERS, "workout_start"
                item.update({column: number(row[label], label) for column, label in mapping.items()})
                if item[key] in seen:
                    raise ValueError("duplicate record timestamp")
                seen.add(item[key])
                records.append(item)
            except ValueError as exc:
                raise ValueError(f"{filename}:{line}: {exc}") from exc
        result[table] = records
    keys = {row["cycle_start"] for row in result["cycles"]}
    main_sleep_cycles = set()
    for table in ("sleeps", "workouts"):
        for row in result[table]:
            if row["cycle_start"] not in keys:
                raise ValueError(f"{table}: cycle reference missing from physiological_cycles.csv")
            if table == "sleeps" and not row["nap"]:
                if row["cycle_start"] in main_sleep_cycles:
                    raise ValueError("multiple main sleeps for one cycle")
                main_sleep_cycles.add(row["cycle_start"])
    return result


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        value = value.isoformat()
    if "\x00" in value:
        raise ValueError("NUL character in CSV text")
    return "'" + value.replace("'", "''") + "'"


def render_sql(data):
    lines = ["\\set ON_ERROR_STOP on", "SET standard_conforming_strings = on;", "BEGIN;",
             "SELECT pg_advisory_xact_lock(5742667);"]
    for table, rows in data.items():
        key = {"cycles": "cycle_start", "sleeps": "sleep_start", "workouts": "workout_start"}[table]
        columns = list(rows[0])
        values = ",\n".join("(" + ",".join(literal(row[k]) for k in columns) + ")" for row in rows)
        updates = ",".join(f"{k}=EXCLUDED.{k}" for k in columns if k != key)
        lines.append(f"INSERT INTO whoop.{table} ({','.join(columns)}) VALUES\n{values}\n"
                     f"ON CONFLICT ({key}) DO UPDATE SET {updates};")
    counts = ",".join(str(len(data[k])) for k in ("cycles", "sleeps", "workouts"))
    lines += [f"INSERT INTO whoop.imports (cycles,sleeps,workouts) VALUES ({counts});", "COMMIT;"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--context", default="proxmox")
    parser.add_argument("--namespace", default="monitoring")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="import through kubectl exec")
    mode.add_argument("--sql", action="store_true", help="emit private SQL to stdout")
    args = parser.parse_args()
    try:
        data = load_export(args.folder)
        sql = render_sql(data)
        if args.sql:
            sys.stdout.write(sql)
            return
        if args.apply:
            subprocess.run([
                "kubectl", "--context", args.context, "--namespace", args.namespace,
                "exec", "-i", "deployment/whoop-postgres", "--",
                "psql", "--username=postgres", "--dbname=whoop", "--quiet", "--set=ON_ERROR_STOP=1",
            ], input=sql, text=True, check=True, stdout=subprocess.DEVNULL)
        print(json.dumps({"status": "imported" if args.apply else "validated (no changes)",
                          **{table: len(rows) for table, rows in data.items()},
                          "naps": sum(row["nap"] for row in data["sleeps"])}, ensure_ascii=False))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"WHOOP import failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
