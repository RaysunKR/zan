import os

SECRET_KEY = os.environ.get("SECRET_KEY", "benchmark-secret")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tfb:tfb@localhost:5432/tfb")
