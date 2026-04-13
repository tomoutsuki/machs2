CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS fabeo;
CREATE SCHEMA IF NOT EXISTS aes_gcm;
CREATE SCHEMA IF NOT EXISTS tde;
CREATE SCHEMA IF NOT EXISTS column_level;
CREATE SCHEMA IF NOT EXISTS app_level;

CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  username TEXT UNIQUE NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  attributes JSONB NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.session_usk (
  session_id UUID PRIMARY KEY,
  username TEXT NOT NULL,
  usk_ref TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.policy_examples (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  policy_name TEXT UNIQUE NOT NULL,
  resource_type TEXT NOT NULL,
  policy_expression TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION create_mode_table(schema_name TEXT) RETURNS VOID AS $$
BEGIN
  EXECUTE format('
    CREATE TABLE IF NOT EXISTS %I.entries (
      entry_id UUID PRIMARY KEY,
      resource_type TEXT NOT NULL,
      policy_expression TEXT NOT NULL,
      epoch_label TEXT NOT NULL,
      owner_username TEXT NOT NULL,
      bidx_name TEXT,
      bidx_cpf TEXT,
      bidx_birthdate TEXT,
      encrypted_payload BYTEA NOT NULL,
      iv BYTEA,
      auth_tag BYTEA,
      wrapped_key BYTEA,
      wrapped_key_meta JSONB,
      mode_meta JSONB NOT NULL DEFAULT ''{}''::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )', schema_name
  );

  EXECUTE format('CREATE INDEX IF NOT EXISTS %I_entries_bidx_name_idx ON %I.entries (bidx_name)', schema_name, schema_name);
  EXECUTE format('CREATE INDEX IF NOT EXISTS %I_entries_bidx_cpf_idx ON %I.entries (bidx_cpf)', schema_name, schema_name);
  EXECUTE format('CREATE INDEX IF NOT EXISTS %I_entries_bidx_birthdate_idx ON %I.entries (bidx_birthdate)', schema_name, schema_name);
  EXECUTE format('CREATE INDEX IF NOT EXISTS %I_entries_resource_type_idx ON %I.entries (resource_type)', schema_name, schema_name);
  EXECUTE format('CREATE INDEX IF NOT EXISTS %I_entries_created_at_idx ON %I.entries (created_at)', schema_name, schema_name);
END;
$$ LANGUAGE plpgsql;

SELECT create_mode_table('fabeo');
SELECT create_mode_table('aes_gcm');
SELECT create_mode_table('tde');
SELECT create_mode_table('column_level');
SELECT create_mode_table('app_level');

DROP FUNCTION create_mode_table(TEXT);
