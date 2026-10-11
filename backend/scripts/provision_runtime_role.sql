-- Review and execute using an administrator, ONLY after environment approval.
-- No credentials here. Set a password separately using psql \password.
CREATE ROLE assistant_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
-- Run against the intended database; never grant membership in privileged roles.
DO $$ BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO assistant_runtime', current_database());
END $$;
-- The migration grants table access. If public schema CREATE is inherited from
-- PUBLIC, review that environment separately; do not broadly revoke platform ACLs.
