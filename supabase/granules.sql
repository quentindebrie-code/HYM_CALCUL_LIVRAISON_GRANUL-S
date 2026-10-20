-- Shared cockpit snapshot. Only the Streamlit server may access these objects.
create table public.granules_state (
    id text primary key check (id = 'cockpit'),
    payload jsonb,
    revision bigint not null default 0 check (revision >= 0),
    updated_at timestamptz not null default now(),
    constraint granules_payload_object check (
        payload is null or (
            jsonb_typeof(payload) = 'object'
            and payload @> '{"schema_version": 1}'::jsonb
            and jsonb_typeof(payload->'grille') = 'object'
            and jsonb_typeof(payload->'historique') = 'array'
        )
    )
);
alter table public.granules_state enable row level security;
revoke all on public.granules_state from public, anon, authenticated;
grant select, update on public.granules_state to service_role;
insert into public.granules_state (id) values ('cockpit');

create function public.granules_save_state(p_payload jsonb, p_expected_revision bigint)
returns bigint
language plpgsql security invoker
set search_path = ''
as $$
declare v_revision bigint;
begin
    if p_payload is null then
        raise exception 'Payload required' using errcode = '22023';
    end if;
    update public.granules_state
       set payload = p_payload, revision = revision + 1, updated_at = clock_timestamp()
     where id = 'cockpit' and revision = p_expected_revision
     returning revision into v_revision;
    if not found then
        raise sqlstate 'PT409' using message = 'Concurrent update: reload before saving';
    end if;
    return v_revision;
end;
$$;
revoke all on function public.granules_save_state(jsonb, bigint) from public, anon, authenticated;
grant execute on function public.granules_save_state(jsonb, bigint) to service_role;
comment on table public.granules_state is 'Internal pellet cockpit: tariff grid and price history, server access only.';
