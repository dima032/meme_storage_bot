import sqlite3

def create_connection():
    """ create a database connection to the SQLite database
        and ensure the table exists.
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect("/app/db/memes.db")
        # Ensure the table is created every time we connect
        create_table(conn)
        return conn
    except sqlite3.Error as e:
        print(e)

    return conn


def create_table(conn):
    """ create a table from the create_table_sql statement
    :param conn: Connection object
    :return:
    """
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS memes (
                id integer PRIMARY KEY,
                file_path text NOT NULL,
                tags text
            );
        """)
    except sqlite3.Error as e:
        print(e)


def insert_meme(conn, meme):
    """
    Create a new meme into the memes table
    :param conn:
    :param meme:
    :return: meme id
    """
    sql = ''' INSERT INTO memes(file_path,tags)
              VALUES(?,?) '''
    cur = conn.cursor()
    cur.execute(sql, meme)
    conn.commit()
    return cur.lastrowid


def find_memes_by_tag(conn, tag):
    """
    Query memes by tag
    :param conn: the Connection object
    :param tag:
    :return:
    """
    cur = conn.cursor()
    cur.execute("SELECT * FROM memes WHERE tags LIKE ?", ('%' + tag + '%',))

    rows = cur.fetchall()

    return rows


def get_all_memes(conn):
    """
    Query all memes
    :param conn: the Connection object
    :return:
    """
    cur = conn.cursor()
    cur.execute("SELECT * FROM memes")

    rows = cur.fetchall()

    return rows


def meme_exists(conn, file_path):
    """
    Check if a meme with the given file_path exists
    :param conn: the Connection object
    :param file_path:
    :return:
    """
    cur = conn.cursor()
    cur.execute("SELECT * FROM memes WHERE file_path=?", (file_path,))

    rows = cur.fetchall()

    return len(rows) > 0


def clear_database(conn):
    """
    Clear all memes from the database
    :param conn: the Connection object
    :return:
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM memes")
    conn.commit()


