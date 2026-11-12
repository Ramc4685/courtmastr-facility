import pytest

from app.cli import lane_env_text, lane_names

MAIN = "FH_ENV=dev\nFH_DB_NAME=facilityhub\nFH_API_PORT=8100\nFH_PAYMENTS_PROVIDER=stripe\nFH_STRIPE_SECRET_KEY=x\nFH_REDIS_URL=r\n"


def test_lane_env_swaps_database_ports_and_drops_payments() -> None:
    lines = lane_env_text(MAIN, "p12a").splitlines()
    assert "FH_ENV=dev" in lines and "FH_REDIS_URL=r" in lines
    assert "FH_DB_NAME=facilityhub_p12a" in lines and "FH_TEST_DB_NAME=facilityhub_p12a_test" in lines
    assert "FH_DB_NAME=facilityhub" not in lines
    assert not any(line.startswith(("FH_PAYMENTS_PROVIDER", "FH_STRIPE_")) for line in lines)
    assert sum(line.startswith("FH_API_PORT=") for line in lines) == 1
    assert lane_env_text(MAIN, "p12a") == lane_env_text(MAIN, "p12a")  # stable ports per lane


def test_lane_env_explicit_ports() -> None:
    lines = lane_env_text(MAIN, "x", 8301, 5301).splitlines()
    assert "FH_API_PORT=8301" in lines and "FH_WEB_PORT=5301" in lines


@pytest.mark.parametrize("bad", ["", "P12", "a-b", "a;drop", "x" * 41])
def test_lane_names_reject_unsafe(bad: str) -> None:
    with pytest.raises(SystemExit):
        lane_names(bad)
