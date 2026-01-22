CREATE TABLE public.service_processors (
    service_id smallint NOT NULL,
    processor_id smallint NOT NULL,
    CONSTRAINT service_processors_pkey PRIMARY KEY (service_id, processor_id)
);

ALTER TABLE public.service_processors OWNER TO admin;
