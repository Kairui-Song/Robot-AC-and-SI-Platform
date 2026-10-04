import comm_logger


def test_record_test_event_stores_log_entry():
    comm_logger._log_entries.clear()

    entry = comm_logger.record_test_event('left_leg', '开始执行测试', '正常')

    entries = comm_logger.get_entries()
    assert len(entries) == 1
    assert entries[0]['target'] == 'left_leg'
    assert entries[0]['event'] == '开始执行测试'
    assert entry['level'] == '正常'
