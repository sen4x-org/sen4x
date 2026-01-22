INSERT INTO costs.config VALUES ('processor.l2a.maja.remove-fre', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2a.maja.remove-sre', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2a.optical.cog-tiffs', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2a.optical.compress-tiffs', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2a.optical.num-workers', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.cloud_optimized_geotiff_output', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_brightness', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_fapar', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_fcover', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_in_domain_flags', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_lai', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_ndvi', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.filter.produce_ndwi', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.generate_models', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.lai.use_inra_version', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3b.lai.use_lai_bands_cfg', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.compute.amplitude', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.compute.coherence', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.copy.locally', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.crop.nodata', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.crop.output', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.extract.histogram', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.gpt.parallelism', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.gpt.tile.cache.size', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.join.amplitude.steps', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.join.coherence.steps', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.keep.intermediate', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.min.intersection', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.output.format', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.parallelism', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.pixel.spacing', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.polarisations', 1, 10);
INSERT INTO costs.config VALUES ('processor.l2s1.process.newest', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.fapar_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.fcover_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.lai_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.ndvi_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.s1_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.stats_avg_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.stats_max_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.stats_mean_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.stats_median_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.stats_min_enabled', 1, 10);
INSERT INTO costs.config VALUES ('processor.l3_gen_comp.stats_w_avg_enabled', 1, 10);


INSERT INTO costs.processor VALUES (1, 0);
INSERT INTO costs.processor VALUES (3, 0);
INSERT INTO costs.processor VALUES (5, 1);
INSERT INTO costs.processor VALUES (6, 1);
INSERT INTO costs.processor VALUES (7, 0);
INSERT INTO costs.processor VALUES (8, 1);
INSERT INTO costs.processor VALUES (9, 1);
INSERT INTO costs.processor VALUES (10, 1);
INSERT INTO costs.processor VALUES (11, 1);
INSERT INTO costs.processor VALUES (14, 1);
INSERT INTO costs.processor VALUES (21, 1);


INSERT INTO costs.product_type VALUES (7, 819.200000000000045, 0, true, NULL);
INSERT INTO costs.product_type VALUES (3, 1638.40000000000009, 20, true, 3);
INSERT INTO costs.product_type VALUES (10, 1024, 45, true, 7);
INSERT INTO costs.product_type VALUES (11, 1024, 45, true, 7);
INSERT INTO costs.product_type VALUES (30, 1024, 45, true, 22);
INSERT INTO costs.product_type VALUES (31, 1024, 45, true, 22);
INSERT INTO costs.product_type VALUES (1, 2355.19999999999982, 30, true, 1);

INSERT INTO costs.resource_type VALUES (1, 'machine', 'Virtual or physical machine');
INSERT INTO costs.resource_type VALUES (2, 'hdd', 'HDD storage');
INSERT INTO costs.resource_type VALUES (3, 'ssd', 'SSD storage');
INSERT INTO costs.resource_type VALUES (4, 'nvme', 'NVMe storage');
INSERT INTO costs.resource_type VALUES (5, 'swift', 'Object storage');

INSERT INTO costs.resources VALUES ('hm.2xlarge', 1, '16CPU, 128GB RAM, 384GB SSD Network Storage', 551.019999999999982, 0.900000000000000022);
INSERT INTO costs.resources VALUES ('hmd.xlarge', 1, '8CPU, 64GB RAM, 200GB SSD Local Storage', 280.180000000000007, 0.458000000000000018);
INSERT INTO costs.resources VALUES ('hdd', 2, '8TB HDD Magnetic Storage', 327.680000000000007, NULL);
INSERT INTO costs.resources VALUES ('object_storage', 5, '1TB Object Storage', 20.4800000000000004, NULL);
INSERT INTO costs.resources VALUES ('master_vm', 2, '4 TB HDD storage for master VM', 163.840000000000003, NULL);

