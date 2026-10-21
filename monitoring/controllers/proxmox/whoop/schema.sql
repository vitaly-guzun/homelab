\set ON_ERROR_STOP on
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS whoop;

CREATE TABLE IF NOT EXISTS whoop.cycles (
  cycle_start timestamptz PRIMARY KEY,
  cycle_end timestamptz,
  timezone_offset text NOT NULL,
  recovery numeric,
  resting_hr numeric,
  hrv_ms numeric,
  skin_temp_c numeric,
  spo2 numeric,
  day_strain numeric,
  energy_cal numeric,
  max_hr numeric,
  average_hr numeric
);

CREATE TABLE IF NOT EXISTS whoop.sleeps (
  sleep_start timestamptz PRIMARY KEY,
  cycle_start timestamptz NOT NULL REFERENCES whoop.cycles(cycle_start),
  sleep_end timestamptz NOT NULL,
  timezone_offset text NOT NULL,
  local_start timestamp NOT NULL,
  local_end timestamp NOT NULL,
  nap boolean NOT NULL,
  performance numeric,
  respiratory_rate numeric,
  asleep_min numeric,
  in_bed_min numeric,
  light_min numeric,
  deep_min numeric,
  rem_min numeric,
  awake_min numeric,
  need_min numeric,
  debt_min numeric,
  efficiency numeric,
  consistency numeric
);
CREATE INDEX IF NOT EXISTS whoop_sleeps_cycle ON whoop.sleeps(cycle_start);
CREATE INDEX IF NOT EXISTS whoop_sleeps_end ON whoop.sleeps(sleep_end);

CREATE TABLE IF NOT EXISTS whoop.workouts (
  workout_start timestamptz PRIMARY KEY,
  cycle_start timestamptz NOT NULL REFERENCES whoop.cycles(cycle_start),
  workout_end timestamptz NOT NULL,
  timezone_offset text NOT NULL,
  local_start timestamp NOT NULL,
  duration_min numeric,
  activity text NOT NULL,
  strain numeric,
  energy_cal numeric,
  max_hr numeric,
  average_hr numeric,
  zone1_pct numeric,
  zone2_pct numeric,
  zone3_pct numeric,
  zone4_pct numeric,
  zone5_pct numeric,
  gps_enabled boolean NOT NULL
);
CREATE INDEX IF NOT EXISTS whoop_workouts_cycle ON whoop.workouts(cycle_start);

CREATE TABLE IF NOT EXISTS whoop.imports (
  imported_at timestamptz PRIMARY KEY DEFAULT clock_timestamp(),
  cycles integer NOT NULL,
  sleeps integer NOT NULL,
  workouts integer NOT NULL
);

-- One cycle remains one row even if it contains naps or multiple workouts.
-- The original local wake date is preserved separately from the UTC instant.
CREATE OR REPLACE VIEW whoop.daily AS
SELECT c.*, COALESCE(s.sleep_end, c.cycle_end, c.cycle_start) AS time,
       s.local_end::date AS local_date,
       s.local_start AS local_bedtime, s.local_end AS local_wake,
       s.sleep_start, s.sleep_end, s.performance, s.respiratory_rate,
       s.asleep_min, s.in_bed_min, s.light_min, s.deep_min, s.rem_min,
       s.awake_min, s.need_min, s.debt_min, s.efficiency, s.consistency
FROM whoop.cycles c
LEFT JOIN LATERAL (
  SELECT * FROM whoop.sleeps s
  WHERE s.cycle_start = c.cycle_start AND NOT s.nap
  ORDER BY s.sleep_end DESC LIMIT 1
) s ON true;

GRANT USAGE ON SCHEMA whoop TO whoop_grafana;
GRANT SELECT ON ALL TABLES IN SCHEMA whoop TO whoop_grafana;
ALTER DEFAULT PRIVILEGES IN SCHEMA whoop GRANT SELECT ON TABLES TO whoop_grafana;
COMMIT;
