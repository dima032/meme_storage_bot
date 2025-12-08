import sqlite3

def create_connection():
    """ create a database connection to the SQLite database
        and ensure the table exists.
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect("/app/data/db/memes.db", check_same_thread=False)
        # Ensure the table is created and migrated every time we connect
        create_table(conn)
        return conn
    except sqlite3.Error as e:
        print(e)

    return conn


def create_table(conn):
    """ create a table and migrate schema to use content_hash """
    try:
        c = conn.cursor()
        # Create the table if it doesn't exist
        c.execute("""
            CREATE TABLE IF NOT EXISTS memes (
                id integer PRIMARY KEY,
                file_path text NOT NULL,
                tags text
            );
        """)
        
        # Schema migration from file_unique_id to content_hash
        c.execute("PRAGMA table_info(memes);")
        columns = [col[1] for col in c.fetchall()]
        
        if 'file_unique_id' in columns:
            # Rename column if the old one exists
            c.execute("ALTER TABLE memes RENAME COLUMN file_unique_id TO content_hash;")
        elif 'content_hash' not in columns:
            # Add the column if it doesn't exist at all
            c.execute("ALTER TABLE memes ADD COLUMN content_hash TEXT;")
        
        # Create a unique index to enforce uniqueness on the new column
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_content_hash ON memes (content_hash);")

    except sqlite3.Error as e:
        print(e)


def insert_meme(conn, meme_data):
    """
    Create a new meme into the memes table
    :param conn:
    :param meme_data: A tuple containing (content_hash, file_path, tags)
    :return: meme id
    """
    sql = ''' INSERT INTO memes(content_hash, file_path, tags)
              VALUES(?,?,?) '''
    cur = conn.cursor()
    cur.execute(sql, meme_data)
    conn.commit()
    return cur.lastrowid


def get_all_memes(conn):
    """
    Query all memes
    :param conn: the Connection object
    :return:
    """
    cur = conn.cursor()
    cur.execute("SELECT id, file_path, tags, content_hash FROM memes")
    rows = cur.fetchall()
    return rows


def get_all_hashes(conn):
    """
    Query all content hashes
    :param conn: the Connection object
    :return: A set of all content_hash values
    """
    cur = conn.cursor()
    cur.execute("SELECT content_hash FROM memes WHERE content_hash IS NOT NULL")
    rows = cur.fetchall()
    return {row[0] for row in rows}


def clear_database(conn):
    """
    Clear all memes from the database
    :param conn: the Connection object
    :return:
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM memes")
    conn.commit()


