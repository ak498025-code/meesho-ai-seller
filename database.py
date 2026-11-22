import os
import psycopg2
from psycopg2.extras import DictCursor

class Database:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        finally:
            self.connection.close()

    def execute(self, sql, params=None):
        cursor = self.connection.cursor()
        cursor.execute(sql.replace("?", "%s"), params or ())
        return cursor

    def executescript(self, script):
        cursor = self.connection.cursor()
        for statement in script.split(";"):
            if statement.strip():
                cursor.execute(statement)
        return cursor

def get_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured. Add your Render PostgreSQL Internal Database URL in the web service environment.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    connection = psycopg2.connect(url, cursor_factory=DictCursor)
    return Database(connection)
