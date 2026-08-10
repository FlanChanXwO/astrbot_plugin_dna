"""定时任务调度边界测试。"""

import asyncio


def test_parse_hhmm_accepts_config_shapes_and_uses_declared_defaults():
    from dnaby.scheduler import _parse_hhmm

    assert _parse_hhmm("08:30") == (8, 30)
    assert _parse_hhmm([9, 45]) == (9, 45)
    assert _parse_hhmm("not-a-time", 2, 7) == (2, 7)
    assert _parse_hhmm("24:00", 2, 7) == (2, 7)


def test_start_scheduled_tasks_creates_all_registered_loops(monkeypatch):
    from dnaby import scheduler

    async def no_loop(*args):
        return None

    monkeypatch.setattr(scheduler, "_run_daily", no_loop)
    monkeypatch.setattr(scheduler, "_run_hourly", no_loop)
    monkeypatch.setattr(scheduler, "_run_loop", no_loop)

    async def scenario():
        tasks = await scheduler.start_scheduled_tasks()
        assert [task.get_name() for task in tasks] == [
            "dnaby_auto_sign",
            "dnaby_clear_sign_record",
            "dnaby_mh_push",
            "dnaby_ann_check",
        ]
        await asyncio.gather(*tasks)

    asyncio.run(scenario())


def test_start_scheduled_tasks_wires_business_callbacks(monkeypatch):
    """四个调度循环必须绑定到对应业务回调，而不是只创建空任务。"""
    from dnaby import scheduler

    calls = []

    async def capture_daily(name, factory, hour, minute):
        calls.append(("daily", name, factory.__name__, hour, minute))

    async def capture_hourly(name, factory, minute, second):
        calls.append(("hourly", name, factory.__name__, minute, second))

    async def capture_loop(name, factory, interval):
        calls.append(("loop", name, factory.__name__, interval))

    monkeypatch.setattr(scheduler, "_run_daily", capture_daily)
    monkeypatch.setattr(scheduler, "_run_hourly", capture_hourly)
    monkeypatch.setattr(scheduler, "_run_loop", capture_loop)

    async def scenario():
        tasks = await scheduler.start_scheduled_tasks()
        await asyncio.gather(*tasks)

    asyncio.run(scenario())

    assert [call[:3] for call in calls] == [
        ("daily", "auto_sign", "dna_auto_sign"),
        ("daily", "clear_sign_record", "clear_dna_sign_record"),
        ("hourly", "mh_push", "dna_push_mh_notify"),
        ("loop", "ann_check", "check_dna_ann_state"),
    ]
