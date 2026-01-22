-- drop function sp_get_vegetation_statistics(integer, character varying, boolean);
CREATE OR REPLACE FUNCTION sp_get_vegetation_statistics(_site_id integer, IN _name character varying,
													   IN _exactMatch boolean DEFAULT false)
  RETURNS TABLE(product_id integer, product_date timestamp with time zone, statistics json) AS
$BODY$
    BEGIN
		if _exactMatch then 
			RETURN QUERY 
			with SimplifiedPrdName as (
--				select CONCAT(substring(_name, 0, 4), '_', substring(_name, 12, 15), '_', substring(_name, 34, 11) )
                select CONCAT((string_to_array(_name, '_'))[1], '_', (string_to_array(_name, '_'))[3], '_', (string_to_array(_name, '_'))[5], '_', (string_to_array(_name, '_'))[6])
			)
			SELECT product.id AS product_id, product.created_timestamp as product_date, l3_veg_stats.stats as statistics
								FROM l3_veg_stats inner join product on (product.id = l3_veg_stats.l2a_product_id)
					where l3_veg_stats.site_id = _site_id and 
						  l3_veg_stats.simplified_l2a_name in (select * from SimplifiedPrdName);
		else 
			RETURN QUERY 
			with InPrdInfos (orbit, tile, date) as (
				select substring(_name, 35, 3)::int, 
						substring(_name, 40, 5),
						substring(_name, 12, 15)
			)
			SELECT product.id AS product_id, product.created_timestamp as product_date, l3_veg_stats.stats as statistics
								FROM l3_veg_stats inner join product on (product.id = l3_veg_stats.l2a_product_id)
					where l3_veg_stats.site_id = _site_id and 
						  l3_veg_stats.tile in (select tile from InPrdInfos) and 
						  l3_veg_stats.orbit in (select orbit from InPrdInfos) and 
						  product.created_timestamp <= (select date::timestamptz from InPrdInfos)
						  order by product.created_timestamp desc limit 1;
		end if;
    END;
$BODY$
LANGUAGE plpgsql VOLATILE
COST 100
ROWS 1000;
ALTER FUNCTION sp_get_vegetation_statistics(integer, character varying, boolean)
  OWNER TO admin; 