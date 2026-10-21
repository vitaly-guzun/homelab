\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE sleep_schedule_test (LIKE whoop.sleeps INCLUDING ALL);
INSERT INTO sleep_schedule_test
  (sleep_start, sleep_end, cycle_start, timezone_offset, local_start, local_end, nap)
VALUES
  ('2026-10-20 21:30:00Z', '2026-10-21 05:30:00Z', '2026-10-20 20:00:00Z',
   'UTC+02:00', '2026-10-20 23:30:00', '2026-10-21 07:30:00', false),
  ('2026-10-21 04:30:00Z', '2026-10-21 12:00:00Z', '2026-10-21 04:00:00Z',
   'UTC-04:00', '2026-10-21 00:30:00', '2026-10-21 08:00:00', false);
DO $test$
BEGIN
  ASSERT (SELECT bedtime_night_seconds = 84600 AND wake_night_seconds = 113400
          FROM sleep_schedule_test WHERE timezone_offset = 'UTC+02:00'), 'Evening-to-morning coordinates';
  ASSERT (SELECT bedtime_night_seconds = 88200 AND wake_night_seconds = 115200
          FROM sleep_schedule_test WHERE timezone_offset = 'UTC-04:00'), 'After-midnight bedtime and travel';
  ASSERT (SELECT avg(bedtime_night_seconds) = 86400 FROM sleep_schedule_test), '23:30 and 00:30 average to midnight';
END;
$test$;

-- Same ON CONFLICT pattern as the importer: generated values update themselves.
INSERT INTO sleep_schedule_test
  (sleep_start, sleep_end, cycle_start, timezone_offset, local_start, local_end, nap)
VALUES ('2026-10-20 21:30:00Z', '2026-10-21 06:00:00Z', '2026-10-20 20:00:00Z',
        'UTC+02:00', '2026-10-20 23:30:00', '2026-10-21 08:00:00', false)
ON CONFLICT (sleep_start) DO UPDATE SET local_end = EXCLUDED.local_end, sleep_end = EXCLUDED.sleep_end;
SET LOCAL TIME ZONE 'America/New_York';
UPDATE sleep_schedule_test SET local_start = local_start;
DO $test$
BEGIN
  ASSERT (SELECT count(*) = 2 FROM sleep_schedule_test), 'Upsert must not duplicate a sleep';
  ASSERT (SELECT bedtime_night_seconds = 84600 AND wake_night_seconds = 115200
          FROM sleep_schedule_test WHERE timezone_offset = 'UTC+02:00'), 'Upsert recomputes wake without timezone shift';
  ASSERT NOT EXISTS (
    SELECT FROM whoop.sleeps
    WHERE bedtime_night_seconds % 86400 <> extract(hour FROM local_start)::integer * 3600
        + extract(minute FROM local_start)::integer * 60 + extract(second FROM local_start)::integer
       OR wake_night_seconds % 86400 <> extract(hour FROM local_end)::integer * 3600
        + extract(minute FROM local_end)::integer * 60 + extract(second FROM local_end)::integer
       OR wake_night_seconds - bedtime_night_seconds <> extract(epoch FROM local_end - local_start)::integer
  ), 'Existing observations retain original local clocks and interval lengths';
  ASSERT NOT has_table_privilege('whoop_grafana', 'whoop.sleeps', 'INSERT,UPDATE'), 'Reader stays read-only';
END;
$test$;
SET LOCAL ROLE whoop_grafana;
DO $test$
BEGIN
  ASSERT (SELECT count(*) = 0 FROM whoop.sleep_schedule('2200-01-01Z', '2200-02-01Z')), 'Empty range';
  ASSERT (SELECT count(*) > 0 FROM whoop.sleep_schedule('2000-01-01Z', '2100-01-01Z')), 'Reader can query schedule';
END;
$test$;
ROLLBACK;
