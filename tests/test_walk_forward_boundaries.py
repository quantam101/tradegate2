import pytest

from runtime.tradegate.events import Tick
from runtime.tradegate.optimizer import walk_forward_windows


def frames(times):
    return [Tick('X', t, 100, 99, 101, 1, 1, 0) for t in times]


def test_simultaneous_frames_stay_on_one_side_of_split():
    ticks = frames([0, 1, 2, 2, 2, 3, 4, 5])
    train, test = walk_forward_windows(ticks, n_windows=1, train_frac=0.5)[0]
    assert train[-1].timestamp < test[0].timestamp
    assert train + test == ticks


@pytest.mark.parametrize('kwargs', [
    {'n_windows': 0}, {'n_windows': -1}, {'n_windows': 1.5},
    {'train_frac': 0}, {'train_frac': 1}, {'train_frac': float('nan')},
    {'n_windows': 100},
])
def test_invalid_or_empty_windows_rejected(kwargs):
    with pytest.raises(ValueError):
        walk_forward_windows(frames(range(8)), **kwargs)


@pytest.mark.parametrize('times', [[2, 1, 3, 4], [0, 1, float('nan'), 3], [1]*8])
def test_invalid_timeline_or_unsplittable_group_rejected(times):
    with pytest.raises(ValueError):
        walk_forward_windows(frames(times), n_windows=1)


def test_valid_rolling_windows_are_nonempty_and_chronological():
    windows = walk_forward_windows(frames(range(40)))
    assert len(windows) == 3
    for train, test in windows:
        assert train and test
        assert train[-1].timestamp < test[0].timestamp
