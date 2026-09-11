import pytest
from app.isolated_runner import read_result


def test_job_outputs_cannot_follow_symlinks_or_exceed_limits(tmp_path):
    secret = tmp_path / "outside"
    secret.write_text("private")
    link = tmp_path / "submission.csv"
    link.symlink_to(secret)
    with pytest.raises(OSError):
        read_result(link, 100)
    with pytest.raises(ValueError):
        read_result(secret, 2)
    assert read_result(secret, 100) == b"private"
