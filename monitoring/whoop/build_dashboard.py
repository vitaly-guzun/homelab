#!/usr/bin/env python3
"""Build the Git-provisioned WHOOP dashboard (no personal data embedded)."""
import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "whoop-postgres"}
PANELS = []
NEXT_ID = 1
ACTIVITY = "activity IN (${activity:sqlstring})"
RECOVERY_COLORS = {"Green (≥67%)": "#16E600", "Yellow (34–66%)": "#FFDE00", "Red (≤33%)": "#FF0038"}


def override(name, **properties):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": key, "value": value} for key, value in properties.items()]}


def panel(title, kind, x, y, w, h, sql=None, unit="none", description="", options=None, custom=None):
    global NEXT_ID
    p = {"id": NEXT_ID, "title": title, "type": kind, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "description": description,
         "fieldConfig": {"defaults": {"unit": unit, "noValue": "N/A",
                                       "color": {"mode": "palette-classic"}}, "overrides": []},
         "options": options or {}}
    NEXT_ID += 1
    if sql:
        p["datasource"] = DS
        p["targets"] = [{"refId": "A", "datasource": DS, "rawQuery": True,
                         "editorMode": "code", "format": "time_series" if kind == "timeseries" else "table",
                         "rawSql": sql}]
    if kind == "timeseries":
        p["fieldConfig"]["defaults"]["custom"] = {
            "drawStyle": "line", "lineInterpolation": "linear", "lineWidth": 2,
            "fillOpacity": 8, "showPoints": "auto", "pointSize": 5,
            "spanNulls": False, "axisPlacement": "auto", "stacking": {"mode": "none", "group": "A"},
            **(custom or {})}
        p["options"] = {"tooltip": {"mode": "multi", "sort": "none"},
                        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}}
    PANELS.append(p)
    return p


def row(title, y):
    p = panel(title, "row", 0, y, 24, 1)
    p.update(collapsed=False, panels=[])
    return p


def stack_full_width(panels, start_y=0):
    """Keep visual order and give each panel its own 24-column row."""
    cursor = start_y
    for p in sorted(panels, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"])):
        p["gridPos"].update(x=0, y=cursor, w=24)
        cursor += p["gridPos"]["h"]
        if p.get("panels"):
            child_end = stack_full_width(p["panels"], cursor)
            if not p.get("collapsed"):
                cursor = child_end
    return cursor


def daily_sql(fields, condition="true"):
    return f'SELECT time AS "time", {fields} FROM whoop.daily WHERE $__timeFilter(time) AND {condition} ORDER BY time'


def moving_average(p, column):
    # Each Grafana time range chooses a trailing window; no observation values
    # are embedded in the dashboard. Read a full warm-up window before the range.
    days = """CASE
    WHEN $__timeTo()::timestamptz - $__timeFrom()::timestamptz <= interval '14 days' THEN 1
    WHEN $__timeTo()::timestamptz - $__timeFrom()::timestamptz <= interval '45 days' THEN 3
    WHEN $__timeTo()::timestamptz - $__timeFrom()::timestamptz <= interval '120 days' THEN 7
    WHEN $__timeTo()::timestamptz - $__timeFrom()::timestamptz <= interval '240 days' THEN 14
    ELSE 30 END"""
    sql = f'''WITH history AS (
  SELECT time, avg({column}) OVER (
    ORDER BY time RANGE BETWEEN ({days}) * interval '24 hours' PRECEDING AND CURRENT ROW
  ) AS average FROM whoop.daily
  WHERE time >= $__timeFrom()::timestamptz - ({days}) * interval '24 hours'
    AND time <= $__timeTo()::timestamptz AND {column} IS NOT NULL
)
SELECT time AS "time", average AS value, 'AVG · ' || ({days})::text || '-day window' AS metric
FROM history WHERE $__timeFilter(time) ORDER BY time'''
    p["targets"].append({"refId": "B", "datasource": DS, "rawQuery": True,
                         "editorMode": "code", "format": "time_series", "rawSql": sql})
    style = override("unused", **{
        "color": {"mode": "fixed", "fixedColor": "#FFFFFF"},
        "custom.drawStyle": "line", "custom.lineWidth": 2, "custom.fillOpacity": 0,
        "custom.lineStyle": {"fill": "dash", "dash": [6, 4]}, "custom.showPoints": "never"})
    style["matcher"] = {"id": "byFrameRefID", "options": "B"}
    p["fieldConfig"]["overrides"].append(style)
    p["description"] += (" Dashed AVG is a trailing mean of recorded observations, including history before the visible range. "
                         "Window follows selected range: ≤14 days → 1 day; ≤45 → 3 days; ≤120 → 7 days; "
                         "≤240 → 14 days; longer → 30 days. The legend shows the active window. Missing values are not zero-filled.")
    return p


def weekly_ctes():
    return f'''WITH filtered AS (
  SELECT *, date_trunc('week', local_start)::date AS week_start
  FROM whoop.workouts WHERE $__timeFilter(workout_start) AND {ACTIVITY}
), bounds AS (
  SELECT least(date_trunc('week', $__timeFrom()::timestamptz AT TIME ZONE 'Europe/Amsterdam')::date,
               (SELECT min(week_start) FROM filtered)) AS first_week,
         greatest(date_trunc('week', $__timeTo()::timestamptz AT TIME ZONE 'Europe/Amsterdam')::date,
                  (SELECT max(week_start) FROM filtered)) AS last_week
), weeks AS (
  SELECT generate_series(first_week::timestamp, last_week::timestamp, interval '1 week')::date AS week_start
  FROM bounds
), labelled_weeks AS (
  SELECT week_start, to_char(week_start, 'DD.MM') || '–' || to_char(week_start + 6, 'DD.MM.YYYY') ||
    CASE WHEN week_start::timestamp AT TIME ZONE 'Europe/Amsterdam' < $__timeFrom()::timestamptz
           OR (week_start + 7)::timestamp AT TIME ZONE 'Europe/Amsterdam' > $__timeTo()::timestamptz
         THEN ' *' ELSE '' END AS week_label FROM weeks
)'''


def weekly_bars(title, x, sql, description):
    p = panel(title, "barchart", x, 54, 12, 12, sql, "suffix: h", description,
              options={"orientation": "vertical", "xField": "Week", "stacking": "normal", "showValue": "never",
                       "groupWidth": 0.8, "barWidth": 0.9, "xTickLabelRotation": -90, "xTickLabelSpacing": 0,
                       "tooltip": {"mode": "multi", "sort": "desc"},
                       "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}})
    p["fieldConfig"]["defaults"].update(min=0, decimals=2,
        custom={"lineWidth": 0, "fillOpacity": 100, "gradientMode": "none", "axisPlacement": "auto", "axisLabel": "Hours"})
    return p


def trend(title, column, label, unit, x, y):
    return moving_average(panel(title, "timeseries", x, y, 12, 8,
                                daily_sql(f'{column} AS "{label}"'), unit), column)


def sleep_schedule():
    return panel("Time in bed · sleep schedule", "volkovlabs-echarts-panel", 0, 45, 24, 11,
        "SELECT * FROM whoop.sleep_schedule($__timeFrom()::timestamptz, $__timeTo()::timestamptz)",
        description="One blue interval per main sleep, from local bedtime to local wake time. "
        "Dashed lines show selected-period mean bedtime and wake time. Clock values and averages come from PostgreSQL. "
        "Time in bed includes awake time; the date is the original local wake date.",
        options={"editorMode": "code", "renderer": "canvas", "map": "none",
                 "getOption": Path(__file__).with_name("sleep_schedule.js").read_text(encoding="utf-8")})


def build():
    PANELS.clear()
    global NEXT_ID
    # Preserve existing graph IDs after removing the eight summary panels.
    NEXT_ID = 9
    row("Recovery & daily load", 11)
    p = panel("Recovery", "timeseries", 0, 12, 24, 10, '''SELECT time AS "time",
  CASE WHEN recovery >= 67 THEN recovery END AS "Green (≥67%)",
  CASE WHEN recovery >= 34 AND recovery < 67 THEN recovery END AS "Yellow (34–66%)",
  CASE WHEN recovery < 34 THEN recovery END AS "Red (≤33%)"
FROM whoop.daily WHERE $__timeFilter(time) AND recovery IS NOT NULL ORDER BY time''', "percent",
              "One solid-color bar per recorded cycle. Green ≥67%, yellow 34–66%, red ≤33%.",
              custom={"drawStyle": "bars", "fillOpacity": 100, "lineWidth": 0,
                      "gradientMode": "none", "showPoints": "never", "barAlignment": 0, "barWidthFactor": 0.7})
    p["fieldConfig"]["defaults"].update(min=0, max=100, decimals=0)
    for label, color in RECOVERY_COLORS.items():
        p["fieldConfig"]["overrides"].append(override(label, color={"mode": "fixed", "fixedColor": color}))
    moving_average(p, "recovery")
    p = panel("Day Strain", "timeseries", 12, 12, 12, 8, daily_sql('day_strain AS "Day Strain"'),
              description="WHOOP Day Strain is not the sum of workout Strain. Open cycles remain N/A.",
              custom={"drawStyle": "bars", "fillOpacity": 65, "lineWidth": 0})
    p["fieldConfig"]["defaults"].update(min=0, max=21)
    moving_average(p, "day_strain")
    trend("Heart rate variability", "hrv_ms", "HRV", "ms", 0, 20)
    trend("Resting heart rate", "resting_hr", "Resting HR", "bpm", 12, 20)
    row("Sleep", 28)
    p = panel("Main sleep vs sleep need", "timeseries", 0, 29, 12, 8,
              daily_sql('asleep_min * 60 AS "Asleep", need_min * 60 AS "Sleep need"'), "dthms",
              "Main sleep only. Sleep need and Sleep debt are distinct WHOOP export metrics.")
    p["fieldConfig"]["overrides"].append(override("Asleep", **{"custom.drawStyle": "bars", "custom.fillOpacity": 65}))
    panel("Main sleep stages", "timeseries", 12, 29, 12, 8,
          daily_sql('light_min * 60 AS "Light", deep_min * 60 AS "Deep", rem_min * 60 AS "REM"'),
          "dthms", "Aggregate stage duration per main sleep; no within-night hypnogram is available.",
          custom={"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 0, "stacking": {"mode": "normal", "group": "A"}})
    p = panel("Sleep performance, efficiency & consistency", "timeseries", 0, 37, 12, 8,
              daily_sql('performance AS "Performance", efficiency AS "Efficiency", consistency AS "Consistency"'), "percent")
    p["fieldConfig"]["defaults"].update(min=0, max=100)
    panel("Sleep debt", "timeseries", 12, 37, 12, 8, daily_sql('debt_min * 60 AS "Sleep debt"'),
          "dthms", "WHOOP Sleep debt as exported, without summing across days.")
    sleep_schedule()
    NEXT_ID += 1  # Reserve removed Naps panel ID 20; keep later panel links stable.
    row("Training · activity filter applies here", 53)
    p = weekly_bars("Weekly activity volume", 0, weekly_ctes() + ''', activities AS (
  SELECT DISTINCT activity FROM filtered
), volume AS (
  SELECT week_start, activity, sum(duration_min) / 60.0 AS hours FROM filtered GROUP BY 1, 2
)
SELECT w.week_label AS "Week", a.activity AS "Activity", coalesce(v.hours, 0) AS "Hours"
FROM labelled_weeks w CROSS JOIN activities a
LEFT JOIN volume v ON v.week_start = w.week_start AND v.activity = a.activity
ORDER BY w.week_start, a.activity''',
        "Stacked hours per activity, grouped by Monday–Sunday of the original local workout date. "
        "Labels show the calendar week; * marks a week only partly inside the selected period. "
        "Only workouts inside the selected range are counted. Weeks without workouts are zero. Activity filter applies.")
    p["transformations"] = [
        {"id": "groupingToMatrix", "options": {"columnField": "Activity", "rowField": "Week", "valueField": "Hours"}},
        {"id": "organize", "options": {"renameByName": {"Week\\Activity": "Week"}}}]
    zones = ",\n  ".join(f'coalesce(sum(f.duration_min * f.zone{i}_pct / 100), 0) / 60.0 AS "Zone {i}"' for i in range(1, 6))
    weekly_bars("Weekly time in reported HR zones", 12, weekly_ctes() + f'''
SELECT w.week_label AS "Week", {zones}
FROM labelled_weeks w LEFT JOIN filtered f ON f.week_start = w.week_start
GROUP BY w.week_start, w.week_label ORDER BY w.week_start''',
        "Stacked estimated hours in reported zones 1–5 per Monday–Sunday week. * marks a partial week; "
        "only workouts inside the selected range are counted. Activity filter applies. "
        "Duration × reported percentage: zones often total less than 100%; the remainder is unclassified, not redistributed. "
        "All-zero zone records are preserved as reported and do not establish zero physiological load.")
    totals = panel("Activity totals", "table", 0, 63, 8, 10, f'''SELECT activity AS "Activity", count(*) AS "Sessions",
  sum(duration_min) * 60 AS "Duration", round(avg(strain), 1) AS "Avg Strain"
FROM whoop.workouts WHERE $__timeFilter(workout_start) AND {ACTIVITY}
GROUP BY activity ORDER BY sum(duration_min) DESC''', options={"showHeader": True, "cellHeight": "sm"})
    p = panel("Workout journal", "table", 8, 63, 16, 10, f'''SELECT workout_start AS "Start", activity AS "Activity",
  duration_min * 60 AS "Duration", strain AS "Strain", energy_cal AS "Calories",
  average_hr AS "Mean HR", max_hr AS "Max HR",
  zone1_pct + zone2_pct + zone3_pct + zone4_pct + zone5_pct AS "Zones %"
FROM whoop.workouts WHERE $__timeFilter(workout_start) AND {ACTIVITY} ORDER BY workout_start DESC''',
          options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False}})
    for p in PANELS[-2:]:
        p["fieldConfig"]["overrides"].append(override("Duration", unit="dthms"))
    for label in ("Mean HR", "Max HR"):
        p["fieldConfig"]["overrides"].append(override(label, unit="bpm"))
    p["fieldConfig"]["overrides"].append(override("Zones %", unit="percent"))
    p["description"] = "Calories use the export's Energy burned (cal) field. Zones % is the sum of reported zones 1–5, without normalization."
    for field, width in [("Activity", 135), ("Sessions", 70), ("Duration", 95), ("Avg Strain", 90)]:
        totals["fieldConfig"]["overrides"].append(override(field, **{"custom.width": width}))
    totals["fieldConfig"]["overrides"].append(override("Avg Strain", decimals=1))
    for field, width in [("Start", 175), ("Activity", 155), ("Duration", 88), ("Strain", 60),
                         ("Calories", 75), ("Mean HR", 80), ("Max HR", 80), ("Zones %", 75)]:
        p["fieldConfig"]["overrides"].append(override(field, **{"custom.width": width}))
    p["fieldConfig"]["overrides"].append(override("Strain", decimals=1))
    row("Additional physiology", 73)
    for x, title, column, label, unit in [
        (0, "Respiratory rate", "respiratory_rate", "Respiration", "none"),
        (8, "Skin temperature", "skin_temp_c", "Skin temperature", "celsius"),
        (16, "Blood oxygen", "spo2", "SpO₂", "percent"),
    ]:
        panel(title, "timeseries", x, 74, 8, 7, daily_sql(f'{column} AS "{label}"'), unit,
              "Recorded WHOOP observations. Respiratory rate is breaths/min. No clinical alert thresholds are configured.")
    relations_row = row("Explore relationships", 81)
    for x, title, sql, unit, description in [
        (0, "Recovery → same-cycle load", '''SELECT recovery AS "Recovery %", day_strain AS "Day Strain"
FROM whoop.daily WHERE $__timeFilter(time) AND recovery IS NOT NULL AND day_strain IS NOT NULL ORDER BY time''',
         "none", "X = morning Recovery %, Y = Day Strain in that same cycle."),
        (8, "Load → next-cycle recovery", '''WITH history AS (
  SELECT time, day_strain, lead(recovery) OVER (ORDER BY cycle_start) AS next_recovery,
         lead(time) OVER (ORDER BY cycle_start) AS next_time FROM whoop.daily
)
SELECT day_strain AS "Day Strain", next_recovery AS "Next recovery %" FROM history
WHERE $__timeFilter(time) AND $__timeFilter(next_time) AND day_strain IS NOT NULL AND next_recovery IS NOT NULL ORDER BY time''',
         "percent", "X = Day Strain, Y = Recovery of the next chronological cycle. Both observations must be within the selected period."),
        (16, "Main sleep → recovery", '''SELECT asleep_min / 60.0 AS "Sleep hours", recovery AS "Recovery %"
FROM whoop.daily WHERE $__timeFilter(time) AND asleep_min IS NOT NULL AND recovery IS NOT NULL ORDER BY time''',
         "percent", "X = main sleep hours, Y = Recovery recorded after that sleep."),
    ]:
        p = panel(title, "xychart", x, 82, 8, 9, sql, unit, description + " Observational association; no causal inference.",
              options={"seriesMapping": "auto", "show": "points", "pointSize": {"fixed": 5},
                       "legend": {"showLegend": False}, "tooltip": {"mode": "single"}})
        x_label, x_unit = [("Recovery %", "percent"), ("Day Strain", "none"), ("Sleep hours", "h")][x // 8]
        p["fieldConfig"]["overrides"].append(override(x_label, unit=x_unit))
    # A collapsed row contains its children rather than leaving them top-level.
    relations_row["panels"] = PANELS[-3:]
    relations_row["collapsed"] = True
    del PANELS[-3:]
    breakdown = panel("Recovery breakdown · selected period", "barchart", 0, 0, 24, 5, '''SELECT 'Recovery' AS "Period",
  count(*) FILTER (WHERE recovery >= 67) AS "Green (≥67%)",
  count(*) FILTER (WHERE recovery >= 34 AND recovery < 67) AS "Yellow (34–66%)",
  count(*) FILTER (WHERE recovery < 34) AS "Red (≤33%)"
FROM whoop.daily WHERE $__timeFilter(time) AND recovery IS NOT NULL''', "short",
        "Counts of recorded cycles by Recovery zone. Each cycle counts once; travel can produce multiple cycles on a local date.",
        options={"orientation": "horizontal", "xField": "Period", "stacking": "normal", "showValue": "never",
                 "groupWidth": 0.3, "barWidth": 1, "tooltip": {"mode": "multi"},
                 "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": ["lastNotNull"]}})
    breakdown["id"] = 1002
    breakdown["fieldConfig"]["defaults"].update(decimals=0, min=0,
        custom={"lineWidth": 0, "fillOpacity": 100, "gradientMode": "none", "axisPlacement": "auto"})
    for label, color in RECOVERY_COLORS.items():
        breakdown["fieldConfig"]["overrides"].append(override(label, color={"mode": "fixed", "fixedColor": color}))
    del PANELS[-1:]
    recovery_index = next(i for i, p in enumerate(PANELS) if p["title"] == "Recovery")
    PANELS.insert(recovery_index + 1, breakdown)
    for i, p in enumerate(PANELS):
        p["gridPos"].update(y=i, x=0)
    stack_full_width(PANELS)
    return {"uid": "whoop-health", "title": "WHOOP · Health & Training", "id": None, "version": 8,
            "schemaVersion": 41, "editable": True, "tags": ["whoop", "health", "training"],
            "timezone": "Europe/Amsterdam", "refresh": "", "time": {"from": "now-180d", "to": "now"},
            "annotations": {"list": []}, "links": [], "panels": PANELS,
            "templating": {"list": [{"name": "activity", "label": "Activity (training panels)", "type": "query",
                "datasource": DS, "query": "SELECT DISTINCT activity FROM whoop.workouts ORDER BY activity",
                "refresh": 1, "multi": True, "includeAll": True, "options": [],
                "current": {"text": "All", "value": "$__all", "selected": True}, "sort": 1}]}}


if __name__ == "__main__":
    dashboard = build()
    target = Path(__file__).resolve().parents[1] / "configs/proxmox/kube-prometheus-stack/whoop-dashboard.yaml"
    payload = json.dumps(dashboard, indent=2, ensure_ascii=False)
    target.write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: whoop-dashboard\n'
                      '  namespace: monitoring\n  labels:\n    grafana_dashboard: "1"\ndata:\n  whoop-health.json: |-\n'
                      + "\n".join("    " + line for line in payload.splitlines()) + "\n", encoding="utf-8")
    print(f"Built {target.name}")
