"""Download official Titanic materials using locally configured Kaggle credentials.

Requires the current kaggle package on Python 3.11+. No submissions are sent.
"""

import argparse
import json
from pathlib import Path
from prepare_titanic import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination", type=Path, default=Path("data/imports/titanic")
    )
    args = parser.parse_args()
    root = args.destination
    # This validates all three original CSVs and refuses conflicting existing files.
    prepare(root / "source", fetch=True)
    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.competitions.types.competition_api_service import (
        ApiGetCompetitionRequest,
        ApiListCompetitionPagesRequest,
    )

    api = KaggleApi()
    api.authenticate()
    with api.build_kaggle_client() as client:
        for name, request_type, method in [
            ("pages", ApiListCompetitionPagesRequest, "list_competition_pages"),
            ("competition", ApiGetCompetitionRequest, "get_competition"),
        ]:
            request = request_type()
            request.competition_name = "titanic"
            data = getattr(client.competitions.competition_api_client, method)(
                request
            ).to_dict()
            (root / f"{name}.json").write_text(json.dumps(data, indent=2))
    # Keep the source API response, including author and exact notebook version.
    from prepare_titanic import authorization, SafeRedirect
    from urllib.request import Request, build_opener

    request = Request(
        "https://www.kaggle.com/api/v1/kernels/pull/alexisbcook/titanic-tutorial",
        headers={"Authorization": authorization()},
    )
    with build_opener(SafeRedirect()).open(request, timeout=60) as response:
        content = response.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Tutorial exceeds the notebook size limit")
    json.loads(content)
    (root / "tutorial.json").write_bytes(content)
    api.kernels_output(
        "alexisbcook/titanic-tutorial", path=str(root / "outputs"), quiet=True
    )
    license_request = Request("https://www.apache.org/licenses/LICENSE-2.0.txt")
    with build_opener(SafeRedirect()).open(license_request, timeout=30) as response:
        (root / "LICENSE-tutorial.txt").write_bytes(response.read(100000))
    print(f"Official materials saved to {root}. Arena has not been modified.")


if __name__ == "__main__":
    main()
