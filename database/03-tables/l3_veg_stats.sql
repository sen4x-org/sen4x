CREATE TABLE l3_veg_stats
(
  l2a_product_id int NOT NULL,
  site_id int NOT NULL,
  simplified_l2a_name character varying(512) NOT NULL,
  tile character varying NOT NULL,
  orbit int NOT NULL,
  stats json NOT NULL,
  CONSTRAINT pk_l3_veg_stats_details PRIMARY KEY (l2a_product_id), 
  CONSTRAINT fk_product FOREIGN KEY (l2a_product_id) REFERENCES product (id) MATCH SIMPLE 
  ON UPDATE NO ACTION ON DELETE CASCADE
)