\set ON_ERROR_STOP on
BEGIN;

-- Derived once on INSERT/UPDATE, including CSV upserts. Original timestamps
-- remain unchanged. Noon is the start of a night, so 00:30 follows 23:30.
ALTER TABLE whoop.sleeps
  ADD COLUMN IF NOT EXISTS bedtime_night_seconds integer GENERATED ALWAYS AS (
    extract(epoch FROM (local_start - local_start::date))::integer
    + CASE WHEN local_start::time < time '12:00' THEN 86400 ELSE 0 END
  ) STORED,
  ADD COLUMN IF NOT EXISTS wake_night_seconds integer GENERATED ALWAYS AS (
    extract(epoch FROM (local_end - local_start::date))::integer
    + CASE WHEN local_start::time < time '12:00' THEN 86400 ELSE 0 END
  ) STORED;

-- Selected-period averages belong in the query, not the import: changing the
-- Grafana time range must recalculate them. All clock coordinates are seconds.
CREATE OR REPLACE FUNCTION whoop.sleep_schedule(range_from timestamptz, range_to timestamptz)
RETURNS TABLE (
  observed_at timestamptz, wake_date text,
  bedtime_seconds integer, wake_seconds integer,
  bedtime_local text, wake_local text,
  time_in_bed_seconds integer, time_in_bed_local text,
  avg_bedtime_seconds integer, avg_wake_seconds integer, avg_time_in_bed_seconds integer,
  avg_bedtime_local text, avg_wake_local text, avg_time_in_bed_local text
)
LANGUAGE sql STABLE PARALLEL SAFE AS $function$
  WITH selected AS (
    SELECT d.time, s.local_start, s.local_end, s.bedtime_night_seconds,
           s.wake_night_seconds, s.in_bed_min
    FROM whoop.daily d JOIN whoop.sleeps s ON s.sleep_start = d.sleep_start
    WHERE d.time >= range_from AND d.time <= range_to
  ), means AS (
    SELECT *, round(avg(bedtime_night_seconds) OVER ())::integer AS mean_bedtime,
              round(avg(wake_night_seconds) OVER ())::integer AS mean_wake,
              round(avg(in_bed_min) OVER () * 60)::integer AS mean_in_bed
    FROM selected
  )
  SELECT time, to_char(local_end, 'YYYY-MM-DD'),
         bedtime_night_seconds, wake_night_seconds,
         to_char(local_start, 'HH24:MI'), to_char(local_end, 'HH24:MI'),
         round(in_bed_min * 60)::integer,
         to_char(make_interval(secs => (in_bed_min * 60)::double precision), 'HH24:MI'),
         mean_bedtime, mean_wake, mean_in_bed,
         to_char(time '00:00' + make_interval(secs => mean_bedtime), 'HH24:MI'),
         to_char(time '00:00' + make_interval(secs => mean_wake), 'HH24:MI'),
         to_char(make_interval(secs => mean_in_bed), 'HH24:MI')
  FROM means ORDER BY time;
$function$;

REVOKE ALL ON FUNCTION whoop.sleep_schedule(timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION whoop.sleep_schedule(timestamptz, timestamptz) TO whoop_grafana;
COMMIT;
