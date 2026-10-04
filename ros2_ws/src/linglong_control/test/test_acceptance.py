from types import SimpleNamespace as NS
import math
import pytest
from linglong_control_tools.acceptance import HoldWindow, cancel_matches


def test_continuous_hold_has_measured_coverage():
    window = HoldWindow([.1, -.2])
    for i in range(12):
        window.add([.1, -.2], [0, 0], i, i * .1)
    assert window.result(1)['samples'] == 12


@pytest.mark.parametrize('positions,velocities', [
    ([0., -.2], [0, 0]), ([.11, -.2], [0, 0]),
    ([.1, -.2], [.03, 0]), ([math.nan, -.2], [0, 0]), ([.1], [0]),
])
def test_jump_motion_or_bad_feedback_cannot_pass(positions, velocities):
    with pytest.raises(ValueError):
        HoldWindow([.1, -.2]).add(positions, velocities, 1, 1)


def test_repeated_frame_cannot_prove_hold():
    window = HoldWindow([.1])
    window.add([.1], [0], 1, 1)
    with pytest.raises(ValueError, match='cycle'):
        window.add([.1], [0], 1, 2)


def test_ten_samples_in_short_burst_are_insufficient():
    window = HoldWindow([.1])
    for i in range(10):
        window.add([.1], [0], i, i * .001)
    with pytest.raises(ValueError, match='coverage'):
        window.result(.6)


def test_empty_observation_fails():
    with pytest.raises(ValueError):
        HoldWindow([.1]).result(.6)


def test_cancellation_must_match_accepted_goal():
    goal_id = NS(uuid=[1, 2])
    response = NS(return_code=0, goals_canceling=[NS(goal_id=NS(uuid=[3, 4]))])
    assert not cancel_matches(response, goal_id)
    response.goals_canceling = [NS(goal_id=goal_id)]
    assert cancel_matches(response, goal_id)
    response.return_code = 1
    assert not cancel_matches(response, goal_id)
