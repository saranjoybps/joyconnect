-- The redirect URI a user registered with the provider when they saved their credentials.
-- Compared with the current PUBLIC_API_BASE_URL to warn when it has changed.
-- Not granted to clients (column privileges on provider_apps stay as in 0004).
alter table public.provider_apps add column if not exists redirect_uri text;
