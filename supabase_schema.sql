-- Run this once in the Supabase SQL editor (Project > SQL Editor > New query).
--
-- IMPORTANT: check the data type of your existing `users.id` column first
-- (Table Editor > users). If it's `uuid`, keep `user_id uuid` below as-is.
-- If it's `bigint`/`int8`, change every `user_id uuid` to `user_id bigint`.

create table if not exists planned_workouts (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  date date not null,
  sport text not null default 'run',
  title text not null,
  description text default '',
  planned_distance_km numeric,
  planned_duration_min integer,
  intensity text default '',
  notes text default '',
  completed boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists activities (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  strava_id bigint,
  date date not null,
  sport text not null default 'run',
  name text default '',
  distance_km numeric default 0,
  duration_min numeric default 0,
  avg_hr numeric,
  max_hr numeric,
  avg_pace_min_km numeric,
  elevation_gain_m numeric,
  raw_json jsonb,
  created_at timestamptz default now(),
  unique (user_id, strava_id)
);

create table if not exists strava_tokens (
  id bigint generated always as identity primary key,
  user_id uuid not null unique,
  athlete_id bigint,
  access_token text not null,
  refresh_token text not null,
  expires_at bigint not null
);

create index if not exists idx_planned_workouts_user_date on planned_workouts (user_id, date);
create index if not exists idx_activities_user_date on activities (user_id, date);

-- If your `users.id` is bigint instead of uuid, run this version instead of the above:
--
-- create table if not exists planned_workouts (
--   id bigint generated always as identity primary key,
--   user_id bigint not null,
--   ... (rest identical, just user_id bigint everywhere)
-- );
