-- 0002_vault_secret_store.sql — functions backing VaultSecretStore
-- (SECRET_STORE=vault). Callable only by the service role.

create extension if not exists supabase_vault with schema vault;

create or replace function public.app_secret_put(p_user_id uuid, p_payload text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id uuid;
begin
  v_id := vault.create_secret(p_payload, 'conn_' || gen_random_uuid()::text,
                              'connection token for ' || p_user_id::text);
  return v_id;
end;
$$;

create or replace function public.app_secret_get(p_id uuid)
returns text
language sql
security definer
set search_path = ''
as $$
  select decrypted_secret from vault.decrypted_secrets where id = p_id;
$$;

create or replace function public.app_secret_delete(p_id uuid)
returns void
language sql
security definer
set search_path = ''
as $$
  delete from vault.secrets where id = p_id;
$$;

revoke all on function public.app_secret_put(uuid, text) from public, anon, authenticated;
revoke all on function public.app_secret_get(uuid) from public, anon, authenticated;
revoke all on function public.app_secret_delete(uuid) from public, anon, authenticated;
grant execute on function public.app_secret_put(uuid, text) to service_role;
grant execute on function public.app_secret_get(uuid) to service_role;
grant execute on function public.app_secret_delete(uuid) to service_role;
