import duckdb
conn = duckdb.connect('land_price.duckdb')
print(conn.execute("SELECT * FROM populations WHERE municipality_code='03201' ORDER BY year").df())
