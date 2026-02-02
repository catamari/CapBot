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

        # Index for primary query we do in /caplist
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cap_query ON cap_events(rsn,cap_timestamp)")

        # TODO: support adding missing columns.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_activity(
                rsn TEXT PRIMARY KEY,
                last_activity_timestamp INTEGER NOT NULL,
                last_query_timestamp INTEGER NOT NULL,
                private TINYINT DEFAULT 0
            )
        """)

        # NOTE: likely won't need an index on user_activity as the table size is fixed to the number of clan members
        # which cannot be more than a few hundred.
    con.close()

def get_db():
    return sqlite3.connect("capdata.db", check_same_thread=True)
