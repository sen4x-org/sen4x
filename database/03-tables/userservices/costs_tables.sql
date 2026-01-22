CREATE SCHEMA IF NOT EXISTS costs;

CREATE TABLE IF NOT EXISTS costs.config (
    key character varying NOT NULL,
    processing_time_min integer NOT NULL,
    product_size_mb_percent integer NOT NULL
);
ALTER TABLE costs.config OWNER TO admin;

CREATE TABLE costs.processor (
    processor_id smallint NOT NULL,
    max_instances smallint DEFAULT 1 NOT NULL
);
ALTER TABLE costs.processor OWNER TO admin;

CREATE TABLE costs.product_type (
    product_type_id smallint NOT NULL,
    estimated_size_mb double precision NOT NULL,
    processing_time_min integer NOT NULL,
    per_acquisition boolean NOT NULL,
    processor_id smallint
);
ALTER TABLE costs.product_type OWNER TO admin;

CREATE TABLE costs.resource_type (
    id smallint NOT NULL,
    name character varying(32) NOT NULL,
    description character varying(100) NOT NULL
);
ALTER TABLE costs.resource_type OWNER TO admin;

CREATE TABLE costs.resources (
    name character varying(100) NOT NULL,
    resource_type smallint NOT NULL,
    description character varying(1024) NOT NULL,
    monthly_cost_eur double precision NOT NULL,
    hourly_cost_eur double precision
);
ALTER TABLE costs.resources OWNER TO admin;

ALTER TABLE ONLY costs.resources
    ADD CONSTRAINT flavor_pkey PRIMARY KEY (name);

ALTER TABLE ONLY costs.processor
    ADD CONSTRAINT processor_pkey PRIMARY KEY (processor_id);

ALTER TABLE ONLY costs.product_type
    ADD CONSTRAINT product_type_pkey PRIMARY KEY (product_type_id);

ALTER TABLE ONLY costs.resource_type
    ADD CONSTRAINT resource_type_pkey PRIMARY KEY (id);

CREATE INDEX fki_fk_public_processor ON costs.product_type USING btree (processor_id);

CREATE INDEX fki_fk_public_product_type ON costs.product_type USING btree (product_type_id);

CREATE INDEX fki_fk_resource_type ON costs.resources USING btree (resource_type);

ALTER TABLE ONLY costs.product_type
    ADD CONSTRAINT fk_public_processor FOREIGN KEY (processor_id) REFERENCES public.processor(id);

ALTER TABLE ONLY costs.product_type
    ADD CONSTRAINT fk_public_product_type FOREIGN KEY (product_type_id) REFERENCES public.product_type(id);

ALTER TABLE ONLY costs.resources
    ADD CONSTRAINT fk_resource_type FOREIGN KEY (resource_type) REFERENCES costs.resource_type(id);

