CREATE TABLE shape_tiles_s2 (
    tile_id character(5) NOT NULL primary key,
    geog geography NOT NULL,
    epsg_code int not null
);
