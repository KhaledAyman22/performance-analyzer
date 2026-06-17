import psycopg2
import requests
import pandas as pd
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "mp",
    "user": "postgres",
    "password": "postgres"
}

# Free API using Yahoo Finance chart endpoint
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# QUERY
# =========================
QUERY = """
WITH CTE AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY ticker_symbol
               ORDER BY created_at
           ) AS rn
    FROM ticker_messages
    WHERE market = 'us'
      AND created_at BETWEEN '2026-05-01 00:00:00+00'
                         AND '2026-05-31 00:00:00+00'
)

SELECT exchange, ticker_symbol, created_at
FROM CTE
WHERE rn = 1;
"""

# =========================
# DB FETCH
# =========================
conn = psycopg2.connect(**DB_CONFIG)

df = pd.read_sql(QUERY, conn)

now = datetime.now(timezone.utc)

conn.close()

# =========================
# FUNCTIONS
# =========================
def get_price_on_date(symbol, target_date):
    """
    Gets close price on specific date using Yahoo Finance
    """
    
    start_ts = int(target_date.timestamp())
    end_ts = start_ts + 86400 * 5

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}"
        f"&period2={end_ts}"
        f"&interval=1d"
    )

    r = requests.get(url, headers=HEADERS)
    data = r.json()

    result = data["chart"]["result"][0]

    closes = result["indicators"]["quote"][0]["close"]

    for close in closes:
        if close is not None:
            return float(close)

    return None


def get_current_price(symbol):
    """
    Gets latest market price
    """

    now = int(datetime.utcnow().timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={now - 86400 * 5}"
        f"&period2={now}"
        f"&interval=1d"
    )

    r = requests.get(url, headers=HEADERS)
    data = r.json()

    result = data["chart"]["result"][0]

    closes = result["indicators"]["quote"][0]["close"]

    closes = [x for x in closes if x is not None]

    if not closes:
        return None

    return float(closes[-1])


# =========================
# PROCESS
# =========================
results = []

from concurrent.futures import ThreadPoolExecutor, as_completed

now = datetime.now(timezone.utc)

def process_row(row):
    exchange = row["exchange"]
    ticker = row["ticker_symbol"]
    created_at = pd.to_datetime(row["created_at"], utc=True)
    symbol = ticker

    try:
        old_price = get_price_on_date(symbol, created_at)
        current_price = get_current_price(symbol)

        if old_price is None or current_price is None:
            return None

        change_pct = ((current_price - old_price) / old_price) * 100

        return {
            "exchange": exchange,
            "ticker": ticker,
            "created_at": created_at,
            "period_days": (now - created_at).total_seconds() / 86400,
            "old_price": round(old_price, 2),
            "current_price": round(current_price, 2),
            "change_pct": round(change_pct, 2)
        }

    except Exception as e:
        print(f"Error with {symbol}: {e}")
        return None


results = []

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_row, row) for _, row in df.iterrows()]

    for f in as_completed(futures):
        res = f.result()
        if res:
            results.append(res)
# =========================
# OUTPUT
# =========================
result_df = pd.DataFrame(results)

result_df.to_csv("ticker_performance.csv", index=False)

print("\nDone.")
print(result_df.head())