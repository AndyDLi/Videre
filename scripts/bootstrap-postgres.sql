-- Fresh installation after migrations, run as the postgres migration owner.
-- Supply database_name with psql -v; set the login password separately.
\set ON_ERROR_STOP on

CREATE ROLE videre_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE :"database_name" TO videre_app;
GRANT USAGE ON SCHEMA videre TO videre_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA videre TO videre_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA videre
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO videre_app;
