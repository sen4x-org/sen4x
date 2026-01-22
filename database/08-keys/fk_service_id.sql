ALTER TABLE service_processors ADD CONSTRAINT fk_service_id FOREIGN KEY (service_id) REFERENCES public.service(id);

