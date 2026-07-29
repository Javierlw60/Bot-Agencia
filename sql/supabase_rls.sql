-- =============================================================================
-- Supabase: habilitar RLS en tablas public (aviso rls_disabled_in_public)
-- =============================================================================
-- Cómo usar:
--   1) Supabase Dashboard → SQL Editor → New query
--   2) Pegá y ejecutá este script completo
--
-- Qué hace:
--   - Activa ROW LEVEL SECURITY en todas las tablas de public
--   - Revoca acceso directo a roles anon / authenticated (API pública)
--   - Crea política de acceso total para service_role (Edge Functions / admin)
--
-- El backend FastAPI (Render) usa DATABASE_URL con el rol postgres/pooler,
-- que en Supabase tiene BYPASSRLS: sigue leyendo/escriiendo sin cambios.
-- =============================================================================

-- 1) Revocar exposición por PostgREST a roles públicos
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL ROUTINES IN SCHEMA public FROM anon, authenticated;

-- Futuras tablas: no heredar grants peligrosos
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- service_role puede usarse desde Edge Functions / Admin API
GRANT USAGE ON SCHEMA public TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON SEQUENCES TO service_role;

-- 2) Habilitar RLS + política service_role en cada tabla public
DO $$
DECLARE
  r RECORD;
  policy_name text := 'service_role_full_access';
BEGIN
  FOR r IN
    SELECT c.relname AS tablename
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'  -- tablas base
      AND c.relname NOT LIKE 'pg_%'
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',
      r.tablename
    );

    -- No forzamos FORCE RLS: el owner/postgres del pooler sigue operando
    -- con BYPASSRLS. Si más adelante querés FORCE, agregá políticas al rol
    -- de conexión de Render.

    IF EXISTS (
      SELECT 1
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = r.tablename
        AND policyname = policy_name
    ) THEN
      EXECUTE format(
        'DROP POLICY %I ON public.%I',
        policy_name,
        r.tablename
      );
    END IF;

    EXECUTE format(
      'CREATE POLICY %I ON public.%I
         FOR ALL
         TO service_role
         USING (true)
         WITH CHECK (true)',
      policy_name,
      r.tablename
    );

    RAISE NOTICE 'RLS OK → public.%', r.tablename;
  END LOOP;
END $$;

-- 3) Verificación rápida (debe listar relrowsecurity = true)
SELECT
  c.relname AS table_name,
  c.relrowsecurity AS rls_enabled,
  c.relforcerowsecurity AS rls_forced,
  (
    SELECT count(*)
    FROM pg_policies p
    WHERE p.schemaname = 'public' AND p.tablename = c.relname
  ) AS policies
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
ORDER BY c.relname;
