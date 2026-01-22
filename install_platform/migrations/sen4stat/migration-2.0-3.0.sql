begin transaction;

do $migration$
declare _statement text;
begin
    raise notice 'running migrations';

    if exists (select * from information_schema.tables where table_schema = 'public' and table_name = 'meta') then
        if exists (select * from meta where version in ('2.0', '3.0')) then

-- ---------------------------- TODO --------------------------------------
    -- For existing sites from 2.0 we should run something like the following after filling  the auxdata tables:
    
                -- INSERT INTO site_auxdata (site_id, auxdata_descriptor_id, year, season_id, auxdata_file_id, file_name, status_id, parameters, output)
                --         SELECT site_id, auxdata_descriptor_id, year, season_id, auxdata_file_id, file_name, 3, parameters, null -- initially the status is 3=NeedsInput
                --             FROM sp_get_auxdata_descriptor_instances(1::smallint, 1::smallint, 2021::integer);
-- ---------------------------- END TODO --------------------------------------
            
            _statement := $str$
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.docker_image', NULL, 'sen4x/sen4cap-processors:5.0.0', '2021-01-14 12:11:21.800537+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4cap-processors:5.0.0';
                
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.export-product-launcher.use_docker', NULL, '1', '2021-01-20 11:44:25.330355+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 1;
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4c-l4a-extract-parcels.use_docker', NULL, '1', '2021-01-20 18:50:52.244303+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 1;
                
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-perm-crops-samples-rasterization.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-perm-crops-extract-inputs.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-perm-crops-build-refl-stack-tif.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-perm-crops-extract-parcels.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-perm-crop-post-processing.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2024-01-11 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';

                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-savitzky-golay.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-extract-weather-features.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-safy-lut.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-safy-optim.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-features-extraction.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-parcels-extraction.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-reference-extraction.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-model.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-crop-types-extraction.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';

                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-esu-extraction.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-esu-aggregate.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-savitzky-golay-wrp.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';

                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-features-extraction-wrp.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-trend-features-extraction.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-su-merge-yearly-features.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('general.orchestrator.s4s-yield-su-model-wrp.docker_image',  NULL, 'sen4x/sen4stat-processors:3.0.0', '2021-02-19 14:43:00.720811+00') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'sen4x/sen4stat-processors:3.0.0';
                
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('processor.l2s1.tiled.tiff', NULL, true, '2022-09-30 10:31:00.501+02') on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'true';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('processor.l2s1.convert.int', NULL, true, '2022-09-30 10:31:00.501+02')  on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'true';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('processor.l2s1.compress.enabled', NULL, true, '2022-09-30 10:31:00.501+02')  on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'true';
                INSERT INTO config(key, site_id, value, last_updated) VALUES ('processor.l2s1.crop.enabled', NULL, true, '2022-09-30 10:31:00.501+02')  on conflict (key, COALESCE(site_id, -1)) DO UPDATE SET value = 'true';
                
            $str$;
            raise notice '%', _statement;
            execute _statement;


           _statement := 'update meta set version = ''3.0'';';
            raise notice '%', _statement;
            execute _statement;
        end if;
    end if;

    raise notice 'complete';
end;
$migration$;

commit;


