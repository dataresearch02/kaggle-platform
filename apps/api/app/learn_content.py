"""Starter exercises and the idempotent upgrade of legacy course data.

`ensure_learning_content` runs at every startup (from seed.py). It converts legacy
lesson JSON into course_lessons rows, maps legacy per-index lesson completion to
lesson_progress, and adds the graded exercises below to the three seeded courses.
ContentReceipt rows make each step run once, so authors can later edit or delete
converted lessons and seeded exercises without them coming back.

Every exercise is solvable offline with packages in the runtime image. Pandas and
machine learning exercises read practice packs from input/<slug>/ (see
practice_inputs.py).
"""

import json
from textwrap import dedent

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .models import (
    Course,
    CourseExercise,
    CourseLesson,
    ContentReceipt,
    LessonProgress,
    Progress,
    now,
)


def code(text):
    return dedent(text).strip() + "\n"


PYTHON_EXERCISES = [
    {
        "lesson": 0,
        "title": "Convert Celsius to Fahrenheit",
        "prompt": (
            "Write a function `to_fahrenheit(celsius)` that returns the temperature in"
            " degrees Fahrenheit, using the formula **F = C × 1.8 + 32**."
        ),
        "starter_code": code(
            """
            def to_fahrenheit(celsius):
                # Replace the line below with the formula
                return 0

            print(to_fahrenheit(20))
            """
        ),
        "hints": [
            "Multiply the Celsius value by 1.8 first.",
            "Then add 32: `return celsius * 1.8 + 32`.",
        ],
        "solution": code(
            """
            def to_fahrenheit(celsius):
                return celsius * 1.8 + 32
            """
        ),
        "checker": code(
            """
            assert callable(globals().get("to_fahrenheit")), "Define a function named to_fahrenheit."
            for celsius, expected in [(0, 32), (100, 212), (-40, -40), (20.5, 68.9)]:
                result = to_fahrenheit(celsius)
                assert isinstance(result, (int, float)), "to_fahrenheit should return a number."
                assert abs(result - expected) < 1e-6, f"to_fahrenheit({celsius}) returned {result}; expected {expected}."
            arena_pass("Correct! to_fahrenheit handles freezing, boiling and negative temperatures.")
            """
        ),
    },
    {
        "lesson": 1,
        "title": "Total rentals without sum()",
        "prompt": (
            "Complete `total_rentals(counts)` so it returns the total of a list of rental"
            " counts. Use a `for` loop instead of the built-in `sum()`. An empty list"
            " totals `0`."
        ),
        "starter_code": code(
            """
            def total_rentals(counts):
                total = 0
                # Loop over counts and add each value to total
                return total

            print(total_rentals([120, 210, 320]))
            """
        ),
        "hints": [
            "Write `for count in counts:` and indent the next line.",
            "Inside the loop, add each value: `total = total + count`.",
        ],
        "solution": code(
            """
            def total_rentals(counts):
                total = 0
                for count in counts:
                    total = total + count
                return total
            """
        ),
        "checker": code(
            """
            import builtins

            assert callable(globals().get("total_rentals")), "Define a function named total_rentals."
            original_sum = builtins.sum

            def forbidden_sum(*args, **kwargs):
                raise AssertionError("Use a for loop instead of sum().")

            builtins.sum = forbidden_sum
            try:
                for counts, expected in [([120, 210, 320], 650), ([], 0), ([5], 5), ([1.5, 2.5], 4.0)]:
                    result = total_rentals(list(counts))
                    assert result == expected, f"total_rentals({counts}) returned {result!r}; expected {expected}."
            finally:
                builtins.sum = original_sum
            arena_pass("Correct! Your loop adds every value, and an empty list totals 0.")
            """
        ),
    },
    {
        "lesson": 2,
        "title": "Convert to several units",
        "prompt": (
            'Write `convert(celsius, unit="F")`. Return Fahrenheit for `"F"` and Kelvin'
            ' (`celsius + 273.15`) for `"K"`. Raise a `ValueError` for any other unit.'
        ),
        "starter_code": code(
            """
            def convert(celsius, unit="F"):
                if unit == "F":
                    return celsius * 1.8 + 32
                # Add Kelvin support and reject unknown units

            print(convert(20), convert(20, "K"))
            """
        ),
        "hints": [
            'Add an `elif unit == "K":` branch that returns `celsius + 273.15`.',
            'Finish with `raise ValueError(f"Unknown unit: {unit}")` for everything else.',
        ],
        "solution": code(
            """
            def convert(celsius, unit="F"):
                if unit == "F":
                    return celsius * 1.8 + 32
                if unit == "K":
                    return celsius + 273.15
                raise ValueError(f"Unknown unit: {unit}")
            """
        ),
        "checker": code(
            """
            assert callable(globals().get("convert")), "Define a function named convert."
            assert abs(convert(20) - 68) < 1e-6, "convert(20) should default to Fahrenheit and return 68."
            assert abs(convert(0, "K") - 273.15) < 1e-6, 'convert(0, "K") should return 273.15.'
            assert abs(convert(-40, unit="F") + 40) < 1e-6, 'convert(-40, unit="F") should return -40.'
            try:
                convert(10, "X")
            except ValueError:
                pass
            else:
                arena_fail('convert(10, "X") should raise ValueError for an unknown unit.')
            arena_pass("Correct! convert supports Fahrenheit and Kelvin and rejects unknown units.")
            """
        ),
    },
]

WINE = "input/wine-cultivar/train.csv"
PANDAS_EXERCISES = [
    {
        "lesson": 0,
        "title": "Inspect the wine data",
        "prompt": (
            f"Load `{WINE}` into a dataframe named `wine`. Set `n_rows` and `n_columns`"
            " to its number of rows and columns, and `missing_values` to the total"
            " number of missing cells."
        ),
        "starter_code": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            print(wine.head())

            n_rows = None
            n_columns = None
            missing_values = None
            """
        ),
        "hints": [
            "`wine.shape` is a `(rows, columns)` tuple.",
            "`wine.isna().sum()` counts missing values per column; sum that again for the"
            " whole table.",
        ],
        "solution": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            n_rows, n_columns = wine.shape
            missing_values = int(wine.isna().sum().sum())
            """
        ),
        "checker": code(
            f"""
            import pandas as pd

            expected = pd.read_csv("{WINE}")
            assert isinstance(globals().get("wine"), pd.DataFrame), "Load the CSV into a dataframe named wine."
            assert wine.shape == expected.shape, f"wine has shape {{wine.shape}}; load the whole training file."
            assert n_rows == expected.shape[0], "n_rows should be the number of rows (hint: wine.shape)."
            assert n_columns == expected.shape[1], "n_columns should be the number of columns."
            assert missing_values == int(expected.isna().sum().sum()), "missing_values should count every missing cell."
            arena_pass(f"Correct! The training data has {{n_rows}} rows and {{n_columns}} columns.")
            """
        ),
        "inputs": ["wine-cultivar"],
    },
    {
        "lesson": 0,
        "title": "Filter and sort",
        "prompt": (
            "Create `strong_wines`: the rows of `wine` whose `alcohol` is above 13.5,"
            " sorted from the highest to the lowest alcohol."
        ),
        "starter_code": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            strong_wines = wine  # Filter and sort here
            print(strong_wines[["alcohol", "cultivar"]].head())
            """
        ),
        "hints": [
            'Filter with a boolean mask: `wine[wine["alcohol"] > 13.5]`.',
            'Sort with `.sort_values("alcohol", ascending=False)`.',
        ],
        "solution": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            strong_wines = wine[wine["alcohol"] > 13.5].sort_values("alcohol", ascending=False)
            """
        ),
        "checker": code(
            f"""
            import pandas as pd

            source = pd.read_csv("{WINE}")
            expected = source[source["alcohol"] > 13.5]
            assert isinstance(globals().get("strong_wines"), pd.DataFrame), "strong_wines should be a dataframe."
            assert "alcohol" in strong_wines.columns and "id" in strong_wines.columns, "Keep the original columns."
            assert (strong_wines["alcohol"] > 13.5).all(), "Keep only rows whose alcohol is above 13.5."
            assert len(strong_wines) == len(expected), f"strong_wines has {{len(strong_wines)}} rows; {{len(expected)}} wines have alcohol above 13.5."
            assert sorted(strong_wines["id"]) == sorted(expected["id"]), "Keep the original rows, including their id column."
            assert strong_wines["alcohol"].is_monotonic_decreasing, "Sort by alcohol from highest to lowest (ascending=False)."
            arena_pass(f"Correct! {{len(strong_wines)}} wines have more than 13.5% alcohol.")
            """
        ),
        "inputs": ["wine-cultivar"],
    },
    {
        "lesson": 1,
        "title": "Average alcohol by cultivar",
        "prompt": (
            "Create `mean_alcohol`, a Series with the mean `alcohol` of each `cultivar`,"
            " using `groupby`. Then set `strongest_cultivar` to the cultivar with the"
            " highest mean."
        ),
        "starter_code": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            mean_alcohol = None
            strongest_cultivar = None
            """
        ),
        "hints": [
            'Group, select a column, then aggregate: `wine.groupby("cultivar")["alcohol"].mean()`.',
            "`Series.idxmax()` returns the index label of the largest value.",
        ],
        "solution": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            mean_alcohol = wine.groupby("cultivar")["alcohol"].mean()
            strongest_cultivar = mean_alcohol.idxmax()
            """
        ),
        "checker": code(
            f"""
            import pandas as pd

            source = pd.read_csv("{WINE}")
            expected = source.groupby("cultivar")["alcohol"].mean()
            assert isinstance(globals().get("mean_alcohol"), pd.Series), "mean_alcohol should be a pandas Series."
            assert sorted(mean_alcohol.index.tolist()) == sorted(expected.index.tolist()), "mean_alcohol needs one value per cultivar."
            for cultivar, value in expected.items():
                assert abs(float(mean_alcohol.loc[cultivar]) - value) < 1e-6, f"The mean alcohol of cultivar {{cultivar}} should be {{value:.3f}}."
            assert strongest_cultivar == expected.idxmax(), "strongest_cultivar should be the cultivar with the highest mean."
            arena_pass(f"Correct! Cultivar {{strongest_cultivar}} has the highest mean alcohol.")
            """
        ),
        "inputs": ["wine-cultivar"],
    },
]

DIABETES = "input/diabetes-progression/train.csv"
ML_EXERCISES = [
    {
        "lesson": 0,
        "title": "Separate features and target",
        "prompt": (
            f"From `{WINE}`, create `X` with every feature column (everything except `id`"
            " and `cultivar`) and `y` with the `cultivar` target."
        ),
        "starter_code": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            X = None
            y = None
            """
        ),
        "hints": [
            '`wine.drop(columns=["id", "cultivar"])` removes columns and returns a new dataframe.',
            'Select the target as a Series: `wine["cultivar"]`.',
        ],
        "solution": code(
            f"""
            import pandas as pd

            wine = pd.read_csv("{WINE}")
            X = wine.drop(columns=["id", "cultivar"])
            y = wine["cultivar"]
            """
        ),
        "checker": code(
            f"""
            import pandas as pd

            source = pd.read_csv("{WINE}")
            features = [column for column in source.columns if column not in ("id", "cultivar")]
            assert isinstance(globals().get("X"), pd.DataFrame), "X should be a dataframe of feature columns."
            assert "cultivar" not in X.columns, "Never include the target (cultivar) in X."
            assert "id" not in X.columns, "The id column identifies rows; it is not a feature."
            assert sorted(X.columns) == sorted(features), f"X should contain the {{len(features)}} chemistry columns."
            assert len(X) == len(source), "Keep every training row in X."
            assert isinstance(globals().get("y"), pd.Series), "y should be the cultivar column as a Series."
            assert y.tolist() == source["cultivar"].tolist(), "y should hold the cultivar of every row."
            arena_pass(f"Correct! X has {{X.shape[1]}} features for {{len(X)}} wines.")
            """
        ),
        "inputs": ["wine-cultivar"],
    },
    {
        "lesson": 1,
        "title": "Validate a classifier",
        "prompt": (
            "Split the wine data with `train_test_split(X, y, test_size=0.25,"
            " random_state=42, stratify=y)`, fit a classifier named `model` on the"
            " training part, and set `accuracy` to its accuracy on the validation part."
            " Reach at least **0.85**."
        ),
        "starter_code": code(
            f"""
            import pandas as pd
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import train_test_split

            wine = pd.read_csv("{WINE}")
            X = wine.drop(columns=["id", "cultivar"])
            y = wine["cultivar"]
            X_train, X_valid, y_train, y_valid = train_test_split(
                X, y, test_size=0.25, random_state=42, stratify=y
            )

            model = RandomForestClassifier(random_state=42)
            # Fit the model on the training rows, then measure validation accuracy
            accuracy = None
            """
        ),
        "hints": [
            "Train with `model.fit(X_train, y_train)`.",
            "`model.score(X_valid, y_valid)` returns the validation accuracy.",
        ],
        "solution": code(
            f"""
            import pandas as pd
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import train_test_split

            wine = pd.read_csv("{WINE}")
            X = wine.drop(columns=["id", "cultivar"])
            y = wine["cultivar"]
            X_train, X_valid, y_train, y_valid = train_test_split(
                X, y, test_size=0.25, random_state=42, stratify=y
            )
            model = RandomForestClassifier(random_state=42)
            model.fit(X_train, y_train)
            accuracy = model.score(X_valid, y_valid)
            """
        ),
        "checker": code(
            f"""
            import pandas as pd
            from sklearn.base import is_classifier
            from sklearn.model_selection import train_test_split

            source = pd.read_csv("{WINE}")
            features = source.drop(columns=["id", "cultivar"])
            target = source["cultivar"]
            _, valid_X, _, valid_y = train_test_split(
                features, target, test_size=0.25, random_state=42, stratify=target
            )
            assert hasattr(globals().get("model"), "predict"), "Create and fit a classifier named model."
            assert is_classifier(model), "model should be a classifier."
            try:
                predictions = model.predict(valid_X)
            except Exception as error:
                arena_fail(f"model.predict failed on the validation rows ({{type(error).__name__}}). Did you call model.fit?")
            actual = float((predictions == valid_y.to_numpy()).mean())
            assert isinstance(accuracy, (int, float)), "Set accuracy to a number between 0 and 1."
            assert abs(float(accuracy) - actual) < 1e-6, f"Measure accuracy on the validation split; the model scores {{actual:.3f}} there."
            assert actual >= 0.85, f"Validation accuracy is {{actual:.3f}}; reach at least 0.85."
            arena_pass(f"Correct! Validation accuracy: {{actual:.3f}}.")
            """
        ),
        "inputs": ["wine-cultivar"],
    },
    {
        "lesson": 2,
        "title": "Measure regression error",
        "prompt": (
            f"Predict diabetes `progression` from `{DIABETES}`. Split with"
            " `train_test_split(X, y, test_size=0.25, random_state=42)`, fit a"
            " regression `model` on the training part and set `rmse` to its"
            " validation RMSE. Beat the baseline: RMSE below **65**."
        ),
        "starter_code": code(
            f"""
            import numpy as np
            import pandas as pd
            from sklearn.linear_model import LinearRegression
            from sklearn.model_selection import train_test_split

            diabetes = pd.read_csv("{DIABETES}")
            X = diabetes.drop(columns=["id", "progression"])
            y = diabetes["progression"]
            X_train, X_valid, y_train, y_valid = train_test_split(
                X, y, test_size=0.25, random_state=42
            )

            model = LinearRegression()
            rmse = None
            """
        ),
        "hints": [
            "Fit on the training rows, then call `model.predict(X_valid)`.",
            "RMSE is `np.sqrt(np.mean((y_valid - predictions) ** 2))`.",
        ],
        "solution": code(
            f"""
            import numpy as np
            import pandas as pd
            from sklearn.linear_model import LinearRegression
            from sklearn.model_selection import train_test_split

            diabetes = pd.read_csv("{DIABETES}")
            X = diabetes.drop(columns=["id", "progression"])
            y = diabetes["progression"]
            X_train, X_valid, y_train, y_valid = train_test_split(
                X, y, test_size=0.25, random_state=42
            )
            model = LinearRegression()
            model.fit(X_train, y_train)
            predictions = model.predict(X_valid)
            rmse = float(np.sqrt(np.mean((y_valid - predictions) ** 2)))
            """
        ),
        "checker": code(
            f"""
            import numpy as np
            import pandas as pd
            from sklearn.base import is_regressor
            from sklearn.model_selection import train_test_split

            source = pd.read_csv("{DIABETES}")
            features = source.drop(columns=["id", "progression"])
            target = source["progression"]
            _, valid_X, _, valid_y = train_test_split(features, target, test_size=0.25, random_state=42)
            assert hasattr(globals().get("model"), "predict"), "Create and fit a regression model named model."
            assert is_regressor(model), "model should be a regressor."
            try:
                predictions = model.predict(valid_X)
            except Exception as error:
                arena_fail(f"model.predict failed on the validation rows ({{type(error).__name__}}). Did you call model.fit?")
            actual = float(np.sqrt(np.mean((valid_y.to_numpy() - predictions) ** 2)))
            assert isinstance(rmse, (int, float)), "Set rmse to a number."
            assert abs(float(rmse) - actual) < 1e-3, f"Measure RMSE on the validation split; the model's RMSE there is {{actual:.2f}}."
            assert actual < 65, f"Validation RMSE is {{actual:.2f}}; get it below 65."
            arena_pass(f"Correct! Validation RMSE: {{actual:.2f}}.")
            """
        ),
        "inputs": ["diabetes-progression"],
    },
]

SEEDED = [
    {
        "slug": "python-foundations",
        "title": "Python foundations",
        "difficulty": "beginner",
        "exercises": PYTHON_EXERCISES,
    },
    {
        "slug": "pandas-essentials",
        "title": "Pandas essentials",
        "difficulty": "beginner",
        "exercises": PANDAS_EXERCISES,
    },
    {
        "slug": "intro-to-machine-learning",
        "title": "Intro to machine learning",
        "difficulty": "intermediate",
        "exercises": ML_EXERCISES,
    },
]


def lesson_markdown(lesson):
    """Legacy lessons had plain text and a code snippet; lessons are now Markdown."""
    body = str(lesson.get("body") or "").strip()
    snippet = str(lesson.get("code") or "").strip()
    if snippet:
        body += f"\n\n```python\n{snippet}\n```"
    return body


def convert_lessons(db):
    for course in db.scalars(select(Course).order_by(Course.id)).all():
        if (course.lessons or "[]").strip() in ("", "[]"):
            continue  # Authored courses have no legacy lesson JSON.
        key = f"learn-lessons-{course.id}-v1"
        if db.get(ContentReceipt, key):
            continue
        if not db.scalar(
            select(CourseLesson.id).where(CourseLesson.course_id == course.id).limit(1)
        ):
            try:
                legacy = json.loads(course.lessons)
            except ValueError:
                legacy = []
            for position, lesson in enumerate(
                legacy if isinstance(legacy, list) else []
            ):
                if not isinstance(lesson, dict):
                    continue
                db.add(
                    CourseLesson(
                        course_id=course.id,
                        position=position,
                        title=str(lesson.get("title") or f"Lesson {position + 1}")[
                            :160
                        ],
                        body=lesson_markdown(lesson),
                        updated_at=now(),
                    )
                )
        db.add(ContentReceipt(key=key, detail=json.dumps({"course": course.id})))
    db.flush()


def convert_progress(db):
    key = "learn-progress-v1"
    if db.get(ContentReceipt, key):
        return
    lessons = {}
    converted = 0
    for user_id, course_id, index in db.execute(
        select(Progress.user_id, Progress.course_id, Progress.lesson_index)
    ).all():
        if course_id not in lessons:
            lessons[course_id] = list(
                db.scalars(
                    select(CourseLesson.id)
                    .where(CourseLesson.course_id == course_id)
                    .order_by(CourseLesson.position, CourseLesson.id)
                )
            )
        ids = lessons[course_id]
        # Legacy rows are unique per (user, course, index), so each maps once.
        if 0 <= index < len(ids) and not db.get(LessonProgress, (user_id, ids[index])):
            db.add(LessonProgress(user_id=user_id, lesson_id=ids[index]))
            converted += 1
    db.add(ContentReceipt(key=key, detail=json.dumps({"converted": converted})))
    db.flush()


def add_seeded_exercises(db):
    for spec in SEEDED:
        key = f"learn-exercises-{spec['slug']}-v1"
        if db.get(ContentReceipt, key):
            continue
        course = db.scalar(
            select(Course).where(Course.title == spec["title"]).order_by(Course.id)
        )
        if course is None:
            continue
        lessons = list(
            db.scalars(
                select(CourseLesson)
                .where(CourseLesson.course_id == course.id)
                .order_by(CourseLesson.position, CourseLesson.id)
            )
        )
        added = 0
        for item in spec["exercises"]:
            if item["lesson"] >= len(lessons):
                continue
            lesson = lessons[item["lesson"]]
            position = db.scalar(
                select(func.count())
                .select_from(CourseExercise)
                .where(CourseExercise.lesson_id == lesson.id)
            )
            db.add(
                CourseExercise(
                    lesson_id=lesson.id,
                    position=position,
                    title=item["title"],
                    prompt=item["prompt"],
                    starter_code=item["starter_code"],
                    hints=json.dumps(item["hints"]),
                    solution=item["solution"],
                    checker=item["checker"],
                    reveal_after=3,
                    inputs=json.dumps(item.get("inputs", [])),
                    updated_at=now(),
                )
            )
            db.flush()
            added += 1
        course.difficulty = spec["difficulty"]
        db.add(
            ContentReceipt(
                key=key, detail=json.dumps({"course": course.id, "exercises": added})
            )
        )
    db.flush()


def ensure_learning_content(db):
    try:
        convert_lessons(db)
        convert_progress(db)
        add_seeded_exercises(db)
        db.commit()
    except IntegrityError:
        # Another API replica recorded the same receipts at the same time.
        db.rollback()
