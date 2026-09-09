import json
from sqlalchemy import select
from .db import DATA_DIR
from .models import User, Dataset, Competition, Notebook, Course, Discussion, ModelCard
from .auth import hash_password
import secrets


def seed(db):
    if db.scalar(select(User).where(User.username == "arena")):
        return
    user = User(
        username="arena", password_hash=hash_password(secrets.token_urlsafe(32))
    )
    db.add(user)
    db.flush()
    uploads = DATA_DIR / "uploads"
    uploads.mkdir(exist_ok=True)
    samples = [
        (
            "City bikes & daily demand",
            "A small synthetic dataset for your first regression model. Explore how weather and working days affect bike rentals.",
            "tabular,regression",
            "id,temperature,working_day,rentals\n1,12,1,120\n2,18,1,210\n3,24,0,320\n4,8,1,80\n5,21,0,280\n6,16,1,180\n",
        ),
        (
            "Seedling measurements",
            "Synthetic measurements for exploring plant growth with pandas and visualizations.",
            "biology,beginner",
            "id,height_cm,days,species\n1,12,20,basil\n2,18,30,basil\n3,8,20,mint\n4,14,30,mint\n",
        ),
        (
            "Neighborhood energy",
            "A tiny synthetic energy-use dataset for experimenting with exploratory data analysis.",
            "energy,tabular",
            "id,temperature,households,kwh\n1,10,20,250\n2,20,20,180\n3,30,20,300\n",
        ),
    ]
    for i, (title, description, tags, content) in enumerate(samples):
        key = f"seed-{i}.csv"
        (uploads / key).write_text(content)
        db.add(
            Dataset(
                owner_id=user.id,
                title=title,
                description=description,
                tags=tags,
                filename=key,
                storage_key=key,
                size=len(content.encode()),
            )
        )
    db.add(
        Competition(
            title="Predict bike demand",
            description="Build your first regression model using the City bikes dataset. Predict rental demand for IDs 7, 8 and 9. Download the test features and sample submission, then upload your predictions. This educational challenge uses synthetic data and a single leaderboard; lower RMSE is better.",
            category="Getting Started",
            metric="RMSE",
            deadline="2027-12-31T23:59:59+00:00",
            solution=json.dumps({"7": 240, "8": 100, "9": 300}),
            prize="Build your first model",
        )
    )
    db.add(
        Notebook(
            owner_id=user.id,
            title="Your first exploratory analysis",
            description="Load a dataset, ask a question, and find your first insight.",
            code='import pandas as pd\n\n# Download City bikes from Datasets and upload it to JupyterLab.\ndf = pd.read_csv("seed-0.csv")\nprint(df.describe())\ndf.plot.scatter(x="temperature", y="rentals")\n',
        )
    )
    courses = [
        (
            "Python foundations",
            "Write your first lines of Python and build confidence with data.",
            "25 min",
            [
                {
                    "title": "Variables and types",
                    "body": "Variables give names to values. Python has integers, floats, strings, and booleans. Run the example in a notebook, then change temperature to 25 and observe the result.",
                    "code": "temperature = 18\ncity = 'Berlin'\nprint(city, temperature * 1.8 + 32)",
                },
                {
                    "title": "Lists and loops",
                    "body": "Lists hold ordered collections. A for loop visits each value. Exercise: calculate the sum of the rentals without using sum().",
                    "code": "rentals = [120, 210, 320]\nfor count in rentals:\n    print(count)\nprint(sum(rentals) / len(rentals))",
                },
                {
                    "title": "Functions",
                    "body": "Functions package reusable steps. Exercise: add a second argument to convert a temperature into a different unit.",
                    "code": "def fahrenheit(celsius):\n    return celsius * 1.8 + 32\n\nprint(fahrenheit(20))",
                },
            ],
        ),
        (
            "Intro to machine learning",
            "Train a baseline model and learn to evaluate predictions.",
            "35 min",
            [
                {
                    "title": "Features and targets",
                    "body": "Features are the inputs to a model. The target is the value to predict. In the bike dataset, temperature and working_day are features; rentals is the target. Never include the target in your input features.",
                    "code": "import pandas as pd\ndf = pd.read_csv('seed-0.csv')\nX = df[['temperature', 'working_day']]\ny = df['rentals']",
                },
                {
                    "title": "Train and validate",
                    "body": "Keep validation rows separate from training rows. This tiny example illustrates the workflow; meaningful evaluation needs substantially more data.",
                    "code": "from sklearn.model_selection import train_test_split\nfrom sklearn.tree import DecisionTreeRegressor\nX_train, X_valid, y_train, y_valid = train_test_split(X, y, random_state=42)\nmodel = DecisionTreeRegressor(max_depth=2, random_state=42)\nmodel.fit(X_train, y_train)\nprint(model.predict(X_valid))",
                },
                {
                    "title": "Make a submission",
                    "body": "Train on your available training data, load the competition test CSV, and save predictions with the exact required column names. RMSE measures prediction error; lower is better.",
                    "code": "model.fit(X, y)\ntest = pd.read_csv('test.csv')\npd.DataFrame({'id': test['id'], 'prediction': model.predict(test[['temperature', 'working_day']])}).to_csv('submission.csv', index=False)",
                },
            ],
        ),
        (
            "Pandas essentials",
            "Turn raw tables into useful answers.",
            "20 min",
            [
                {
                    "title": "Explore a dataframe",
                    "body": "Read your CSV into a dataframe. Inspect its shape, column types, and missing values before analyzing it.",
                    "code": "import pandas as pd\ndf = pd.read_csv('seed-0.csv')\nprint(df.head())\nprint(df.dtypes)\nprint(df.isna().sum())",
                },
                {
                    "title": "Group and summarize",
                    "body": "Group rows by a category and calculate a statistic for each group. Exercise: compare mean rentals on working days with other days.",
                    "code": "print(df.groupby('working_day')['rentals'].mean())",
                },
            ],
        ),
    ]
    for title, description, duration, lessons in courses:
        db.add(
            Course(
                title=title,
                description=description,
                duration=duration,
                lessons=json.dumps(lessons),
            )
        )
    db.add(
        Discussion(
            owner_id=user.id,
            title="Welcome to the learning lab",
            body="What are you building this week? Share your first experiment, ask a question, or help someone get unstuck. All starter datasets here are small synthetic examples.",
        )
    )
    db.add(
        ModelCard(
            owner_id=user.id,
            title="Decision tree regressor",
            description="A useful baseline for tabular regression. This catalog entry links to scikit-learn documentation; it is not a hosted model or downloadable trained artifact.",
            framework="scikit-learn",
            license="BSD-3-Clause",
            url="https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeRegressor.html",
        )
    )
    db.commit()
