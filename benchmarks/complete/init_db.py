import os
import random
import psycopg

DB_URL = os.environ.get("DATABASE_URL", "postgresql://tfb:tfb@localhost:5432/tfb")
FORTUNES = [
    (1, "frame was not set"),
    (2, "A computer scientist is someone who fixes things that aren't broken."),
    (3, "After you learn Esperanto, you'll find that it's a whole new language."),
    (4, "After you learn Esperanto, you'll find that you're a whole new person."),
    (5, "Adding manpower to a late software project makes it later."),
    (6, "All phone calls are obscene."),
    (7, "<script>alert('This should not be displayed in a browser alert box.');</script>"),
    (8, "Day of the tentacle & the wrath of the &amp; entity"),
    (9, "Everything is closer than you think."),
    (10, "Fortune favors the bold <b>HTML</b> & the careful"),
    (11, "Technology is a \"quantitative\" improvement to life."),
    (12, "When the only tool you have is a hammer, everything looks like a nail."),
]

SCHEMA = """
DROP TABLE IF EXISTS world;
DROP TABLE IF EXISTS fortune;
CREATE TABLE world (
    id INTEGER PRIMARY KEY,
    randomnumber INTEGER NOT NULL
);
CREATE TABLE fortune (
    id INTEGER PRIMARY KEY,
    message TEXT NOT NULL
);
"""


def init_db():
    conn = psycopg.connect(DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    rng = random.Random(42)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO world (id, randomnumber) VALUES (%s, %s)",
            [(i, rng.randint(1, 10000)) for i in range(1, 10001)],
        )
        cur.executemany(
            "INSERT INTO fortune (id, message) VALUES (%s, %s)",
            FORTUNES,
        )
    conn.commit()
    conn.close()
    print("Database initialized.")


if __name__ == "__main__":
    init_db()
