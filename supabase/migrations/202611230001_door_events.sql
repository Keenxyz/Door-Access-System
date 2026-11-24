begin;

create table public.door_devices (
    writer_id uuid primary key references auth.users(id) on delete cascade,
    reader_id uuid not null references auth.users(id) on delete cascade,
    check (writer_id <> reader_id)
);

create table public.door_events (
    id uuid not null,
    device_id uuid not null references public.door_devices(writer_id) on delete cascade,
    occurred_at timestamptz not null,
    person text not null,
    result text not null check (result in ('GRANTED', 'DENIED')),
    similarity double precision not null check (similarity between -1 and 1),
    primary key (device_id, id)
);

create index door_events_device_time on public.door_events (device_id, occurred_at desc, id desc);
create index door_devices_reader on public.door_devices (reader_id, writer_id);

alter table public.door_devices enable row level security;
alter table public.door_events enable row level security;

revoke all on public.door_devices, public.door_events from public, anon, authenticated;
grant select on public.door_devices, public.door_events to authenticated;

create policy "Readers see their assigned devices"
on public.door_devices for select to authenticated
using (reader_id = (select auth.uid()));

create policy "Readers see events from their assigned devices"
on public.door_events for select to authenticated
using (device_id in (select writer_id from public.door_devices));

create function public.record_door_events(events jsonb)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    writer uuid := auth.uid();
begin
    if not exists (select 1 from public.door_devices where writer_id = writer) then
        raise exception 'This account cannot submit door events' using errcode = '42501';
    end if;

    if jsonb_typeof(events) is distinct from 'array' then
        raise exception 'Expected an array of events' using errcode = '22023';
    end if;
    if jsonb_array_length(events) not between 1 and 50 then
        raise exception 'Expected 1 to 50 events' using errcode = '22023';
    end if;

    insert into public.door_events (id, device_id, occurred_at, person, result, similarity)
    select event.id, writer, event.occurred_at, event.person, event.result, event.similarity
    from jsonb_to_recordset(events) as event (
        id uuid, occurred_at timestamptz, person text, result text, similarity double precision
    )
    on conflict (device_id, id) do nothing;
end;
$$;

revoke all on function public.record_door_events(jsonb) from public, anon, authenticated;
grant execute on function public.record_door_events(jsonb) to authenticated;

commit;
