import pytest

from app.agents.decision_log import DecisionLog
from app.agents.scout import MAX_WINDOW_S, arrival_window_s, select_landmark
from tests.agent_fakes import landmark, state


def reasons(log):
    return {r["landmark_id"]: r["reason"] for r in log.records}


def test_selects_nearest_ahead():
    far, near = landmark("far", dlat=0.004), landmark("near", dlat=0.002)
    assert select_landmark(state([far, near])).id == "near"


def test_rejection_reasons():
    log = DecisionLog()
    cands = [
        landmark("done"),
        landmark("skipped"),
        landmark("behind", dlat=-0.002),
        landmark("side", dlat=0.0, dlng=0.003),  # 正东，偏离航向 90°
        landmark("far", dlat=0.01),  # 约 1.1 km
        landmark("close", dlat=0.0005),  # 约 55 m，10 m/s 下只有 5.5 s
        landmark("passing", dlat=0.0001),  # 约 11 m
    ]
    s = state(cands, narrated_ids=["done"], skipped_ids=["skipped"])
    assert select_landmark(s, log) is None
    assert reasons(log) == {
        "done": "already_narrated",
        "skipped": "already_skipped",
        "behind": "behind",
        "side": "behind",
        "far": "out_of_range",
        "close": "too_close",
        "passing": "behind",
    }


def test_wraparound_heading_350_target_slightly_east_of_north():
    s = state([landmark("a", dlat=0.002, dlng=0.0005)], heading=350.0)
    assert select_landmark(s).id == "a"


def test_unknown_heading_selects_nothing():
    assert select_landmark(state([landmark("a")], heading=None)) is None


def test_rejections_logged_only_on_change():
    log = DecisionLog()
    s = state([landmark("b", dlat=-0.002)])
    select_landmark(s, log)
    select_landmark(s, log)
    assert len(log.records) == 1


@pytest.mark.parametrize(
    "dist, speed, expected",
    [(200, 10, 20), (1000, 10, MAX_WINDOW_S), (200, 0, MAX_WINDOW_S), (200, 1.5, MAX_WINDOW_S)],
)
def test_arrival_window(dist, speed, expected):
    assert arrival_window_s(dist, speed) == pytest.approx(expected)
