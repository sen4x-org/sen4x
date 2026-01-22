CREATE SCHEMA topology;
ALTER SCHEMA topology OWNER TO admin;

CREATE TABLE topology.node (
    id character varying(250) NOT NULL,
    username character varying(50) NOT NULL,
    password text NOT NULL,
    flavor_id character varying(250) NOT NULL,
    description text,
    ssh_key text,
    role character varying(6) DEFAULT 'worker'::character varying,
    created timestamp without time zone DEFAULT now(),
    modified timestamp without time zone DEFAULT now(),
    volatile boolean DEFAULT false,
    active boolean DEFAULT true
);
ALTER TABLE topology.node OWNER TO admin;

CREATE TABLE topology.node_flavor (
    id character varying(250) NOT NULL,
    cpu integer NOT NULL,
    memory integer NOT NULL,
    disk integer NOT NULL,
    swap integer NOT NULL,
    rxtx real NOT NULL
);
ALTER TABLE topology.node_flavor OWNER TO admin;

ALTER TABLE ONLY topology.node
    ADD CONSTRAINT pk_execution_node PRIMARY KEY (id);

ALTER TABLE ONLY topology.node_flavor
    ADD CONSTRAINT pk_node_flavor PRIMARY KEY (id);

ALTER TABLE ONLY topology.node
    ADD CONSTRAINT fk_execution_node_flavor FOREIGN KEY (flavor_id) REFERENCES topology.node_flavor(id);
