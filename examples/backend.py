from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int):
    return UserResponse(id=user_id, full_name="Ada Lovelace", email="ada@example.com")
