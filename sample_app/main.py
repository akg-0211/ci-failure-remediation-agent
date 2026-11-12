import requests
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def home():
    return {"status": "running"}

@app.get("/add")
def add(a: int, b: int):
    return {"result": a + b}