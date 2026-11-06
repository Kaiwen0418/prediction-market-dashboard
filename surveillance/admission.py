"""Resource-based review admission with working room reserved for in-flight jobs."""


def slots(settings, measured, archive_bytes, active):
    mib = 1024**2
    db_room = min(settings.database_max_bytes*.70-measured.get('database_used_bytes',measured['database_bytes']),
                  settings.database_max_bytes*.90-measured['database_bytes'])
    raw_room = settings.raw_max_bytes*.70-measured['raw_bytes']
    tape_room = settings.research_tape_max_bytes*.75-archive_bytes
    db_reserve = max(512*mib,settings.review_max_trades*4096)
    raw_reserve = max(256*mib,settings.review_max_trades*512)
    archive_reserve = max(256*mib,settings.review_max_trades*1024)
    affordable = max(0, int(min(db_room/db_reserve, raw_room/raw_reserve, tape_room/archive_reserve)))
    available = max(0, min(settings.review_concurrency, affordable)-active)
    return dict(slots=available, active=active, affordable_inflight=affordable,
                database_room_bytes=int(db_room),raw_room_bytes=int(raw_room),archive_room_bytes=int(tape_room),
                reserve_per_job=dict(database_bytes=db_reserve,raw_bytes=raw_reserve,archive_bytes=archive_reserve),
                reason='working_room_available' if available else 'concurrency_or_capacity',
                basis='Conservative admission reserve; ongoing collection remains subject to capacity guard')
