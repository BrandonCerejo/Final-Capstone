from fastapi import APIRouter, HTTPException
from passlib.context import CryptContext
from database import users_collection
from models import RegisterUser, LoginUser

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/register")
def register(user: RegisterUser):

    existing = users_collection.find_one({"email": user.email})

    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed_password = pwd_context.hash(user.password)

    user_data = {
        "name":     user.name,
        "gender":   user.gender,
        "age":      user.age,
        "email":    user.email,
        "password": hashed_password
    }

    users_collection.insert_one(user_data)

    return {"message": "User registered successfully"}


@router.post("/login")
def login(user: LoginUser):

    db_user = users_collection.find_one({"email": user.email})

    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid email")

    valid = pwd_context.verify(user.password, db_user["password"])

    if not valid:
        raise HTTPException(status_code=400, detail="Invalid password")

    return {
        "message": "Login successful",
        "user": {
            "name":   db_user["name"],
            "email":  db_user["email"],
            "age":    db_user.get("age", ""),   
            "gender": db_user.get("gender", ""),
        }
    }