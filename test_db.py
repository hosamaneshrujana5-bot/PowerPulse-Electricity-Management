from database import get_connection

try:
    conn = get_connection()
    print("MySQL connection successful!")

    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")

    print("\nTables available in database:")
    for table in cursor.fetchall():
        print(table[0])

    cursor.close()
    conn.close()

except Exception as e:
    print("Database connection failed!")
    print("Error:", e)