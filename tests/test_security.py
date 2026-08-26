import pytest

from pulseboard.security import validate_target_url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://user:secret@example.com/health",
        "http://127.0.0.1:8000/health",
        "http://[::1]/health",
        "http://169.254.169.254/latest/meta-data",
    ],
)
async def test_unsafe_target_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        await validate_target_url(url, allow_private_targets=False)


async def test_private_target_opt_in_keeps_scheme_and_credential_checks() -> None:
    await validate_target_url("http://127.0.0.1:8000/health", allow_private_targets=True)
    with pytest.raises(ValueError, match="credentials"):
        await validate_target_url(
            "https://user:secret@example.com/health", allow_private_targets=True
        )
