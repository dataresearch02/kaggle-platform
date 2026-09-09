from pydantic import BaseModel, Field, HttpUrl


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=10, max_length=128)


class NotebookInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=5000)
    code: str = Field(max_length=100000)


class DiscussionInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=20000)


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ModelInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=3, max_length=5000)
    framework: str = Field(min_length=1, max_length=80)
    license: str = Field(min_length=1, max_length=80)
    url: HttpUrl


class WorkUpdate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(max_length=5000)
