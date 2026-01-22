CREATE TABLE public.service (
    id serial NOT NULL,
    site_id smallint NOT NULL,
    name character varying NOT NULL,
    footprint_filename character varying,
    additional_support text,
    additional_data_specifications text,
    CONSTRAINT service_pkey PRIMARY KEY (id),
    CONSTRAINT service_site_id_name_key UNIQUE (site_id, name)
);

ALTER TABLE public.service OWNER TO admin;

