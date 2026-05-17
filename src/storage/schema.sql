-- schema.sql
-- DuckDB schema for CardDemo modernization pipeline
-- All node references use stable UUIDs (never string names)
-- 
-- Tables:
--   nodes              -- universal node table (all artifact types)
--   call_graph         -- inter-program CALL + CICS LINK/XCTL edges
--   control_flow       -- CFG edges within programs (Day 4)
--   def_use            -- variable definition + usage chains (Day 4)
--   file_io            -- program -> VSAM file operations (Day 5)
--   db_io              -- program -> DB2 table operations (Day 5)
--   ims_io             -- program -> IMS segment operations (Day 5)
--   mq_io              -- program -> MQ queue operations (Day 5)
--   transaction_flow   -- CICS XCTL/LINK/RETURN edges (Day 5)
--   screen_map         -- BMS map <-> COMMAREA <-> program (Day 5)
--   jcl_job            -- JCL job -> step -> program -> DD (Day 5)
--   jcl_dependency     -- dataset reuse between jobs (Day 5)
--   copybook_use       -- program -> copybook with REPLACING (Day 4)
--   business_rules     -- IF/EVALUATE predicates (Day 6)
--   migration_risk     -- risky constructs for forward engineering (Day 6)

-- ============================================================
-- NODES TABLE (universal — all artifact types)
-- Required by §8: source traceability table
-- ============================================================
CREATE TABLE IF NOT EXISTS nodes (
    uuid            VARCHAR PRIMARY KEY,  -- SHA-256[:32] stable UUID
    kind            VARCHAR NOT NULL,     -- NodeKind enum value
    source_file     VARCHAR NOT NULL,     -- original .cbl/.jcl/.bms file
    start_line      INTEGER NOT NULL,     -- start line (1-indexed)
    end_line        INTEGER NOT NULL,     -- end line (1-indexed)
    start_col       INTEGER DEFAULT 1,    -- start column
    end_col         INTEGER DEFAULT 72,   -- end column
    parent_uuid     VARCHAR,              -- parent node UUID (nullable for roots)
    copybook        VARCHAR,              -- copybook origin if applicable
    payload_json    VARCHAR,                 -- node-specific data (name, pic, etc.)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- SYMBOLS TABLE (Layer 2 — data dictionary)
-- ============================================================
CREATE TABLE IF NOT EXISTS symbols (
    uuid            VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,     -- FK -> nodes.uuid (program)
    name            VARCHAR NOT NULL,     -- variable name
    level           INTEGER,             -- COBOL level number (01-88)
    pic             VARCHAR,             -- PIC clause
    usage           VARCHAR,             -- DISPLAY/COMP/COMP-3 etc
    scope           VARCHAR,             -- WORKING-STORAGE/FILE/LINKAGE
    canonical_type  VARCHAR,                -- normalized type {kind,precision,scale}
    copybook_origin VARCHAR,             -- which copybook if any
    source_file     VARCHAR NOT NULL,
    defined_at_line INTEGER,
    payload_json    VARCHAR
);

-- ============================================================
-- PARAGRAPHS TABLE (Layer 2 — paragraph inventory)
-- ============================================================
CREATE TABLE IF NOT EXISTS paragraphs (
    uuid            VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,     -- FK -> nodes.uuid (program)
    name            VARCHAR NOT NULL,     -- paragraph name
    source_file     VARCHAR NOT NULL,
    start_line      INTEGER,
    end_line        INTEGER,
    line_count      INTEGER,
    statement_count INTEGER DEFAULT 0,
    complexity      INTEGER DEFAULT 1,   -- cyclomatic complexity
    payload_json    VARCHAR
);

-- ============================================================
-- CALL GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS call_graph (
    id              VARCHAR PRIMARY KEY,  -- UUID of this edge
    caller_uuid     VARCHAR NOT NULL,     -- FK -> nodes.uuid (program)
    callee_uuid     VARCHAR NOT NULL,     -- FK -> nodes.uuid (program)
    call_site_uuid  VARCHAR,              -- FK -> nodes.uuid (statement)
    call_type       VARCHAR,             -- CALL/CICS_LINK/CICS_XCTL
    call_target     VARCHAR,             -- literal target name
    is_dynamic      BOOLEAN DEFAULT FALSE,-- dynamic CALL via variable
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- CONTROL FLOW GRAPH (Layer 3)
-- ============================================================
CREATE TABLE IF NOT EXISTS control_flow (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    from_uuid       VARCHAR NOT NULL,     -- source paragraph/statement UUID
    to_uuid         VARCHAR NOT NULL,     -- target paragraph/statement UUID
    edge_type       VARCHAR NOT NULL,     -- PERFORM/IF_TRUE/IF_FALSE/GOTO/FALLTHROUGH
    condition       VARCHAR,             -- condition text if applicable
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- DEF-USE CHAINS (Layer 3)
-- ============================================================
CREATE TABLE IF NOT EXISTS def_use (
    id              VARCHAR PRIMARY KEY,
    data_item_uuid  VARCHAR NOT NULL,     -- FK -> symbols.uuid
    operation       VARCHAR NOT NULL,     -- WRITE/READ
    stmt_uuid       VARCHAR,             -- FK -> nodes.uuid (statement)
    stmt_text       VARCHAR,             -- raw statement text (truncated)
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- FILE I/O GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS file_io (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,     -- FK -> nodes.uuid (program)
    file_name       VARCHAR NOT NULL,     -- VSAM file name (e.g. ACCTDAT)
    operation       VARCHAR NOT NULL,     -- READ/WRITE/REWRITE/DELETE/START/OPEN/CLOSE
    record_copybook VARCHAR,             -- copybook defining the record layout
    stmt_uuid       VARCHAR,             -- FK -> nodes.uuid (statement)
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- DB2 ACCESS GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS db_io (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    table_name      VARCHAR NOT NULL,     -- DB2 table name
    columns         VARCHAR,             -- comma-separated column list
    operation       VARCHAR NOT NULL,     -- SELECT/INSERT/UPDATE/DELETE
    cursor_name     VARCHAR,             -- cursor name if applicable
    stmt_uuid       VARCHAR,
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- IMS ACCESS GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS ims_io (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    segment_name    VARCHAR NOT NULL,
    operation       VARCHAR NOT NULL,     -- GU/GN/GNP/GHU/ISRT/DLET/REPL
    pcb_name        VARCHAR,
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- MQ GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS mq_io (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    queue_name      VARCHAR NOT NULL,
    operation       VARCHAR NOT NULL,     -- PUT/GET
    correlation_id  VARCHAR,
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- TRANSACTION FLOW (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS transaction_flow (
    id              VARCHAR PRIMARY KEY,
    from_program_uuid VARCHAR NOT NULL,
    to_program_uuid   VARCHAR NOT NULL,
    edge_type       VARCHAR NOT NULL,     -- XCTL/LINK/RETURN
    transid         VARCHAR,             -- CICS transaction ID
    commarea_size   INTEGER,
    stmt_uuid       VARCHAR,
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- SCREEN/MAP GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS screen_map (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    map_name        VARCHAR NOT NULL,     -- BMS map name (e.g. COTRN2A)
    mapset_name     VARCHAR NOT NULL,     -- BMS mapset (e.g. COTRN02)
    operation       VARCHAR NOT NULL,     -- SEND_MAP/RECEIVE_MAP
    field_name      VARCHAR,             -- specific field if applicable
    commarea_field  VARCHAR,             -- mapped COMMAREA field
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- JCL JOB GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS jcl_job (
    id              VARCHAR PRIMARY KEY,
    job_name        VARCHAR NOT NULL,
    step_name       VARCHAR NOT NULL,
    program_name    VARCHAR NOT NULL,     -- EXEC PGM=program
    dd_name         VARCHAR,             -- DD statement name
    dataset_name    VARCHAR,             -- dataset referenced
    disposition     VARCHAR,             -- NEW/OLD/MOD/SHR
    steplib         VARCHAR,             -- STEPLIB if applicable
    parm            VARCHAR,             -- PARM value if applicable
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- JCL JOB DEPENDENCY (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS jcl_dependency (
    id              VARCHAR PRIMARY KEY,
    producer_job    VARCHAR NOT NULL,     -- job that creates the dataset
    consumer_job    VARCHAR NOT NULL,     -- job that reads the dataset
    dataset_name    VARCHAR NOT NULL,     -- shared dataset
    producer_disp   VARCHAR,             -- producer disposition
    consumer_disp   VARCHAR              -- consumer disposition
);

-- ============================================================
-- COPYBOOK USAGE GRAPH (Layer 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS copybook_use (
    id              VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,     -- FK -> nodes.uuid (program)
    copybook_name   VARCHAR NOT NULL,
    replacing_rules VARCHAR,                -- REPLACING rules applied
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- BUSINESS RULES (Layer 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS business_rules (
    uuid            VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    kind            VARCHAR NOT NULL,     -- IF/EVALUATE
    predicate_raw   VARCHAR,             -- raw predicate text
    predicate_resolved VARCHAR,             -- resolved with data item UUIDs
    then_summary    VARCHAR,
    else_summary    VARCHAR,
    source_file     VARCHAR,
    line_num        INTEGER
);

-- ============================================================
-- MIGRATION RISK REGISTER (Layer 7)
-- ============================================================
CREATE TABLE IF NOT EXISTS migration_risk (
    uuid            VARCHAR PRIMARY KEY,
    program_uuid    VARCHAR NOT NULL,
    kind            VARCHAR NOT NULL,     -- ALTER/GOTO_DEPENDING/DYNAMIC_CALL/etc
    note            VARCHAR,             -- human-readable explanation
    severity        VARCHAR,             -- low/medium/high
    stmt_uuid       VARCHAR,
    source_file     VARCHAR,
    line_num        INTEGER
);
