begin;

alter table public.door_events
    add column notify boolean not null default false,
    add column lock_command text check (lock_command in ('SECURE_REQUESTED', 'UNVERIFIED')),
    add column photo_path text;

create or replace function public.record_door_events(events jsonb)
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

    insert into public.door_events (id, device_id, occurred_at, person, result, similarity, notify, lock_command)
    select event.id, writer, event.occurred_at, event.person, event.result, event.similarity,
           event.result = 'DENIED' and coalesce(event.notify, false), event.lock_command
    from jsonb_to_recordset(events) as event (
        id uuid, occurred_at timestamptz, person text, result text, similarity double precision,
        notify boolean, lock_command text
    )
    on conflict (device_id, id) do nothing;
end;
$$;

revoke all on function public.record_door_events(jsonb) from public, anon, authenticated;
grant execute on function public.record_door_events(jsonb) to authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('door-visitor-images', 'door-visitor-images', false, 1048576, array['image/jpeg'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create function public.can_upload_door_photo(object_path text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.door_events e
        where e.device_id = (select auth.uid())
          and e.result = 'DENIED'
          and object_path = e.device_id::text || '/' || e.id::text || '.jpg'
    );
$$;

revoke all on function public.can_upload_door_photo(text) from public, anon, authenticated;
grant execute on function public.can_upload_door_photo(text) to authenticated;

create policy "Door writer inserts its own visitor photos"
on storage.objects for insert to authenticated with check (
    bucket_id = 'door-visitor-images'
    and public.can_upload_door_photo(name)
);

create policy "Door writer can repeat its own photo upload"
on storage.objects for update to authenticated using (
    bucket_id = 'door-visitor-images'
    and public.can_upload_door_photo(name)
)
with check (
    bucket_id = 'door-visitor-images'
    and public.can_upload_door_photo(name)
);

create policy "Door writers and assigned readers can read visitor photos"
on storage.objects for select to authenticated using (
    bucket_id = 'door-visitor-images'
    and (
        public.can_upload_door_photo(name)
        or exists (select 1 from public.door_events e where e.photo_path = storage.objects.name)
    )
);

create function public.attach_door_event_photo(event_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    writer uuid := auth.uid();
    expected_path text := writer::text || '/' || event_id::text || '.jpg';
begin
    if not exists (select 1 from storage.objects
                   where bucket_id = 'door-visitor-images' and name = expected_path) then
        raise exception 'Visitor photo not found' using errcode = '22023';
    end if;
    update public.door_events
       set photo_path = expected_path
     where device_id = writer and id = event_id and result = 'DENIED';
    if not found then
        raise exception 'No denied event for this writer' using errcode = '42501';
    end if;
end;
$$;

revoke all on function public.attach_door_event_photo(uuid) from public, anon, authenticated;
grant execute on function public.attach_door_event_photo(uuid) to authenticated;

commit;
