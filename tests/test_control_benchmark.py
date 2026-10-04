from controller.control_benchmark import percentile, summarize


def test_percentile_and_summary_are_calculated_from_samples():
    values = [1.0, 2.0, 3.0, 4.0, 100.0]
    result = summarize(values)
    assert result["count"] == 5
    assert result["mean"] == 22.0
    assert result["max"] == 100.0
    assert result["p50"] == 3.0
    assert percentile(values, 99) > 90


def test_empty_summary_has_no_invented_metrics():
    assert summarize([]) == {"count": 0}
