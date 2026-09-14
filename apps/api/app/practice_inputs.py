"""Practice pack files used as exercise and notebook inputs.

Only train.csv and test.csv are exposed, never solution.csv. A document lists packs in
`metadata.arena_practice_inputs`; each pack is copied to `input/<slug>/`, the same path
in exercise attempts, interactive notebooks and background runs. Slugs come from the
fixed practice_data folder, so they can never name another path.
"""

from pathlib import Path

PRACTICE = Path(__file__).with_name("practice_data")
FILES = ("train.csv", "test.csv")
MAX_INPUTS = 4


def practice_slugs():
    return sorted(
        folder.name for folder in PRACTICE.iterdir() if (folder / "meta.json").is_file()
    )


def validate_slugs(values):
    """Return the known pack slugs in order; raise ValueError for anything else."""
    if not isinstance(values, list) or len(values) > MAX_INPUTS:
        raise ValueError(f"Choose at most {MAX_INPUTS} practice datasets")
    known = set(practice_slugs())
    result = []
    for value in values:
        if not isinstance(value, str) or value not in known:
            raise ValueError(f"Unknown practice dataset: {str(value)[:80]}")
        if value not in result:
            result.append(value)
    return result


def known_slugs(values):
    """Known slugs from untrusted document metadata; unknown entries are ignored."""
    if not isinstance(values, list):
        return []
    known = set(practice_slugs())
    return [value for value in dict.fromkeys(values) if value in known][:MAX_INPUTS]


def practice_files(slugs):
    """(relative path, source file) pairs for the given pack slugs."""
    for slug in known_slugs(slugs):
        for name in FILES:
            yield f"input/{slug}/{name}", PRACTICE / slug / name


def stage_practice_inputs(slugs, work):
    for relative, source in practice_files(slugs):
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
