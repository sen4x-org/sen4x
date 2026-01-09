--DROP FUNCTION public.sp_get_season_for_interval(smallint, date, date);

CREATE OR REPLACE FUNCTION public.sp_get_season_for_interval(
    _site_id     SMALLINT,
    _start_date  DATE,
    _end_date    DATE
)
RETURNS SETOF season
LANGUAGE sql
AS $$
    SELECT s.*
    FROM season s
    WHERE s.site_id = _site_id
      AND _start_date >= s.start_date
      AND _end_date   <= s.end_date;
$$;
