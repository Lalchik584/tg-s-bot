import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional

class Database:
    def __init__(self, db_path: str = "concert_bot.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица мероприятий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    event_date TIMESTAMP NOT NULL,
                    created_by INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
            ''')
            
            # Таблица участников
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    need_reminder BOOLEAN DEFAULT 0,
                    reminder_3days_sent BOOLEAN DEFAULT 0,
                    reminder_12hours_sent BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (event_id) REFERENCES events (id),
                    UNIQUE(event_id, user_id)
                )
            ''')
            
            conn.commit()
    
    def add_event(self, title: str, description: str, event_date: datetime, created_by: int) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO events (title, description, event_date, created_by)
                VALUES (?, ?, ?, ?)
            ''', (title, description, event_date, created_by))
            conn.commit()
            return cursor.lastrowid
    
    def get_event(self, event_id: int) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, title, description, event_date, created_by, created_at, is_active
                FROM events WHERE id = ?
            ''', (event_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'title': row[1],
                    'description': row[2],
                    'event_date': row[3],
                    'created_by': row[4],
                    'created_at': row[5],
                    'is_active': row[6]
                }
            return None
    
    def get_active_events(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, title, description, event_date, created_by, created_at, is_active
                FROM events WHERE is_active = 1 AND event_date > datetime('now')
                ORDER BY event_date
            ''')
            events = []
            for row in cursor.fetchall():
                events.append({
                    'id': row[0],
                    'title': row[1],
                    'description': row[2],
                    'event_date': row[3],
                    'created_by': row[4],
                    'created_at': row[5],
                    'is_active': row[6]
                })
            return events
    
    def add_attendee(self, event_id: int, user_id: int, username: str, 
                     first_name: str, last_name: str, need_reminder: bool = False):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO attendees 
                (event_id, user_id, username, first_name, last_name, need_reminder)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (event_id, user_id, username, first_name, last_name, need_reminder))
            conn.commit()
    
    def update_reminder_status(self, event_id: int, user_id: int, need_reminder: bool):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE attendees 
                SET need_reminder = ?
                WHERE event_id = ? AND user_id = ?
            ''', (need_reminder, event_id, user_id))
            conn.commit()
    
    def get_event_attendees(self, event_id: int) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, event_id, user_id, username, first_name, last_name, 
                       need_reminder, reminder_3days_sent, reminder_12hours_sent, created_at
                FROM attendees WHERE event_id = ?
            ''', (event_id,))
            attendees = []
            for row in cursor.fetchall():
                attendees.append({
                    'id': row[0],
                    'event_id': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'first_name': row[4],
                    'last_name': row[5],
                    'need_reminder': row[6],
                    'reminder_3days_sent': row[7],
                    'reminder_12hours_sent': row[8],
                    'created_at': row[9]
                })
            return attendees
    
    def get_reminders_to_send(self, hours_before: int) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            reminder_field = 'reminder_3days_sent' if hours_before == 72 else 'reminder_12hours_sent'
            
            cursor.execute(f'''
                SELECT a.user_id, a.username, a.first_name, e.id as event_id, 
                       e.title, e.description, e.event_date
                FROM attendees a
                JOIN events e ON a.event_id = e.id
                WHERE a.need_reminder = 1 
                AND {reminder_field} = 0
                AND e.is_active = 1
                AND datetime(e.event_date) BETWEEN datetime('now', '+{hours_before-1} hours') 
                    AND datetime('now', '+{hours_before+1} hours')
            ''')
            
            reminders = []
            for row in cursor.fetchall():
                reminders.append({
                    'user_id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'event_id': row[3],
                    'title': row[4],
                    'description': row[5],
                    'event_date': row[6]
                })
            return reminders
    
    def mark_reminder_sent(self, user_id: int, event_id: int, hours_before: int):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            reminder_field = 'reminder_3days_sent' if hours_before == 72 else 'reminder_12hours_sent'
            cursor.execute(f'''
                UPDATE attendees 
                SET {reminder_field} = 1
                WHERE user_id = ? AND event_id = ?
            ''', (user_id, event_id))
            conn.commit()