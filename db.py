import sqlite3
import logging

def init_db():
    con = sqlite3.connect("capdata.db")
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
    con.close()

def get_db():
    return sqlite3.connect("capdata.db", check_same_thread=True)
