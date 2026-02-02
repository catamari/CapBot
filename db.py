import sqlite3
import logging

def init_db():
    con = sqlite3.connect("capdata.db")
    with con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cap_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rsn TEXT NOT NULL,
                cap_timestamp INTEGER NOT NULL,
                source TEXT,
                manual_user TEXT,
                
                UNIQUE(rsn, cap_timestamp)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_activity(
                rsn TEXT PRIMARY KEY,
                last_activity_timestamp INTEGER NOT NULL,
                last_query_timestamp INTEGER NOT NULL,
                private TINYINT DEFAULT 0
            )
        """)
    con.close()

def get_db():
    return sqlite3.connect("capdata.db", check_same_thread=True)
