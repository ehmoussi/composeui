CREATE TABLE IF NOT EXISTS pipe(
    p_id INTEGER PRIMARY KEY NOT NULL,
    p_name TEXT NOT NULL DEFAULT "PipeTShape",
    export_path TEXT,
    main_radius REAL NOT NULL DEFAULT 80,
    main_width REAL NOT NULL DEFAULT 20,
    main_half_length REAL NOT NULL DEFAULT 200,
    incident_radius REAL NOT NULL DEFAULT 50,
    incident_width REAL NOT NULL DEFAULT 20,
    incident_half_length REAL NOT NULL DEFAULT 200,
    edge_type INTEGER CHECK(edge_type IN (0, 1, 2)) NOT NULL DEFAULT 0,
    chamfer_height REAL NOT NULL DEFAULT 20,
    chamfer_width REAL NOT NULL DEFAULT 10,
    fillet_radius REAL NOT NULL DEFAULT 20
);
