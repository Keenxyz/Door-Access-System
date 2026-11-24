begin;

create table public.door_push_subscriptions (
    endpoint text primary key check (length(endpoint) between 1 and 2048),
    viewer_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    p256dh text not null check (p256dh ~ '^[A-Za-z0-9_-]{80,100}$'),
    auth_key text not null check (auth_key ~ '^[A-Za-z0-9_-]{20,30}$')
);

create index door_push_subscriptions_viewer on public.door_push_subscriptions (viewer_id);
alter table public.door_push_subscriptions enable row level security;
revoke all on public.door_push_subscriptions from public, anon, authenticated;
grant select, insert, update, delete on public.door_push_subscriptions to authenticated, service_role;

create policy "Viewers manage their own phone subscriptions"
on public.door_push_subscriptions to authenticated
using (viewer_id = (select auth.uid()))
with check (
    viewer_id = (select auth.uid())
    and exists (select 1 from public.door_devices d where d.reader_id = (select auth.uid()))
);

grant select on public.door_devices, public.door_events to service_role;

commit;
