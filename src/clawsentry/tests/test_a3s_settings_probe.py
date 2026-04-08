"""Tests for a3s settings runtime probe classification."""

from clawsentry.a3s_settings_probe import classify_settings_probe_result


def test_classify_probe_result_inconclusive_without_runtime():
    result = classify_settings_probe_result(runtime_entrypoint=None, request_count=0)
    assert result.verdict == "inconclusive"
    assert "runtime entrypoint not found" in result.reason


def test_classify_probe_result_supported_when_requests_observed():
    result = classify_settings_probe_result(
        runtime_entrypoint="python-sdk",
        request_count=2,
    )
    assert result.verdict == "supported"
    assert result.request_count == 2


def test_classify_probe_result_not_supported_when_zero_requests():
    result = classify_settings_probe_result(
        runtime_entrypoint="python-sdk",
        request_count=0,
    )
    assert result.verdict == "not_supported"
    assert "no hook traffic observed" in result.reason
