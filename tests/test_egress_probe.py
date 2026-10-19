from src.data.egress_probe import classify, summarize


def test_200_is_ok():
    assert classify(200, 200)[0] == "ok"


def test_451_is_an_error_not_a_quiet_refusal():
    assert classify(451, 451)[0] == "error"
    assert "451" in classify(451, 200)[1]


def test_unreachable_is_an_error():
    out, why = classify(None, None)
    assert out == "error" and "unreachable" in why


def test_summarize_survives_missing_ip_info():
    d = summarize(None, 451, 451)
    assert d["ip"] is None and d["fapi_status"] == 451


def test_summarize_keeps_only_the_named_fields():
    d = summarize({"ip": "1.2.3.4", "country": "SG", "org": "AS1 x", "hostname": "h", "loc": "1,2"}, 200, 200)
    assert d["country"] == "SG" and "hostname" not in d and "loc" not in d
