-- DROP function sp_is_l2_preprocessing_done(smallint, json, timestamp,timestamp)
CREATE OR REPLACE FUNCTION sp_is_l2_preprocessing_done
(
    _site_id site.id%TYPE,
    _sat_ids json,
    _start_date timestamp DEFAULT NULL::timestamp,
    _end_date timestamp DEFAULT NULL::timestamp
  )
  RETURNS boolean AS
$func$

declare _has_s1 boolean;
declare _all_prds_cnt INT:= 0;
declare _s1_not_processed_cnt INT:= 0;
declare _all_enabled boolean;

BEGIN

    -- S1 is a little bit special as it keeps status 2 for products with no previous intersection
	with res(value) as (
    	select 3 = ANY(SELECT value::smallint FROM json_array_elements_text($2))
	)
	select value :: boolean into _has_s1 from res;
	
	if _has_s1 then
        WITH site_config (key, site_id, value) AS (
            SELECT
                keys.key,
                site.id,
                config.value
            FROM site
            CROSS JOIN (
                VALUES
                    ('s1.enabled'),
                    ('processor.l2s1.enabled')
            ) AS keys(key)
            CROSS JOIN LATERAL (
                SELECT COALESCE(
                    (SELECT value FROM config c WHERE c.key = keys.key AND c.site_id = site.id),
                    (SELECT value FROM config c WHERE c.key = keys.key AND c.site_id IS NULL)
                ) AS value
            ) AS config
        )
        SELECT NOT EXISTS (
            SELECT 1
            FROM site_config
            WHERE site_id = _site_id
              AND value::boolean = FALSE
        ) INTO _all_enabled;
    
        if _all_enabled then
            with res0(val0) as (
                -- we need to have some products imported
                select count(*) from downloader_history where 
                        (_start_date is null or product_date >= _start_date) and 
                        (_end_date is null or product_date < _end_date + interval '1 day') and
                        site_id = _site_id and satellite_id = 3        
            )
            select val0 :: int into _all_prds_cnt from res0;
            if _all_prds_cnt = 0 then
                raise notice 'No S1 products downloaded so far!';
                return FALSE;
            end if;
            
            with res1(val1) as (
                select count(*) from downloader_history where 
                    site_id = _site_id and 
                    satellite_id = 3 and
                    (_start_date is null or product_date >= _start_date) and 
                    (_end_date is null or product_date < _end_date + interval '1 day') and
                    ((status_id = 2 and status_reason not like '%No previous product%') OR
                        (status_id in (1,7)))  
            )
            select val1 :: int into _s1_not_processed_cnt from res1;
            raise notice 'A number of % S1 products not processed or with errors (except the ones with No previous product)' , _s1_not_processed_cnt;
            return (_s1_not_processed_cnt = 0);
        else
            return true;
        end if;
    else
        -- Optical - S2, L8, L9 and others. If at least one satellite is processed, we can proceed.
        -- Normally, we should check if each satellite is enabled, the downloader is enabled for it 
        with res0(val0) as (
            -- we need to have some products imported
            select count(*) from downloader_history where 
                    site_id = _site_id and 
                    (_start_date is null or product_date >= _start_date) and 
                    (_end_date is null or product_date < _end_date + interval '1 day') and
                    satellite_id IN (SELECT value::smallint FROM json_array_elements_text($2))
        )
        select val0 :: int into _all_prds_cnt from res0;
        if _all_prds_cnt = 0 then
            raise notice 'No L1 products downloaded so far!';
            return FALSE;
        end if;
        
        RETURN 
        (
            select count(*) from downloader_history 
                where 
                    site_id = _site_id and 
                    satellite_id IN (SELECT value::smallint FROM json_array_elements_text($2)) and 
                    (_start_date is null or product_date >= _start_date) and 
                    (_end_date is null or product_date < _end_date + interval '1 day') and
                    status_id in (1, 2, 7)              -- downloading, not processed or processing 
        )  = 0;
    end if;
END
$func$ LANGUAGE plpgsql STABLE;