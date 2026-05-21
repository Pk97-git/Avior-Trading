"""
analytics/duckdb_engine.py
===========================
DuckDB analytical layer — fast cross-sectional queries over OmniTrader data.

DuckDB reads directly from PostgreSQL via the postgres_scanner extension.
This lets us run analytical SQL (window functions, lateral joins, ranking)
at columnar-scan speed without loading data into memory.

Connection is shared across requests (DuckDB is not thread-safe for concurrent
writes, but for read-only analytics it's fine).

Key queries exposed:
  factor_ranks(date)          → cross-sectional z-score ranks for value/momentum/quality
  rolling_returns(tickers, n) → n-day return for each ticker
  correlation_matrix(tickers) → 90-day pairwise Pearson correlation
  sector_performance(days)    → sector-level avg return
"""
import logging
import os
from datetime import date, timedelta
from typing import Optional

import duckdb
import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)

# Path for persistent DuckDB analytical file (local storage)
DUCKDB_PATH = os.environ.get(
    "DUCKDB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "analytics.duckdb")
)

_conn: Optional[duckdb.DuckDBPyConnection] = None


def _get_pg_dsn() -> str:
    """Build a libpq-compatible DSN for DuckDB's postgres_scanner."""
    s = settings
    return (
        f"host={s.POSTGRES_SERVER} port={s.POSTGRES_PORT} "
        f"dbname={s.POSTGRES_DB} user={s.POSTGRES_USER} "
        f"password={s.POSTGRES_PASSWORD}"
    )


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get or create the shared DuckDB connection."""
    global _conn
    if _conn is None:
        # Ensure data directory exists
        os.makedirs(os.path.dirname(os.path.abspath(DUCKDB_PATH)), exist_ok=True)
        _conn = duckdb.connect(DUCKDB_PATH)
        _setup_extensions(_conn)
        logger.info("DuckDB analytics engine initialized at %s", DUCKDB_PATH)
    return _conn


def _setup_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    """Install and load required extensions."""
    try:
        conn.execute("INSTALL postgres_scanner")
        conn.execute("LOAD postgres_scanner")
        logger.info("DuckDB postgres_scanner extension loaded")
    except Exception as e:
        logger.warning("DuckDB postgres_scanner not available: %s — using direct import mode", e)


def _attach_postgres(conn: duckdb.DuckDBPyConnection) -> bool:
    """Attach PostgreSQL as a read-only source. Returns True if successful."""
    try:
        conn.execute("DETACH IF EXISTS pg")
    except Exception:
        pass
    try:
        dsn = _get_pg_dsn()
        conn.execute(f"ATTACH 'dbname={settings.POSTGRES_DB} host={settings.POSTGRES_SERVER} "
                     f"user={settings.POSTGRES_USER} password={settings.POSTGRES_PASSWORD} "
                     f"port={settings.POSTGRES_PORT}' AS pg (TYPE POSTGRES, READ_ONLY)")
        return True
    except Exception as e:
        logger.warning("DuckDB postgres attach failed: %s", e)
        return False


class DuckDBAnalytics:
    """High-level analytics queries backed by DuckDB."""

    def __init__(self):
        self.conn = get_connection()
        self._pg_attached = _attach_postgres(self.conn)

    def _q(self, sql: str, params: dict = None) -> pd.DataFrame:
        if params:
            return self.conn.execute(sql, list(params.values())).df()
        return self.conn.execute(sql).df()

    def _pg_table(self, table: str) -> str:
        """Return the table reference — pg.public.table if attached, else raise."""
        if self._pg_attached:
            return f"pg.public.{table}"
        raise RuntimeError("PostgreSQL not attached to DuckDB — pg_dsn unavailable")

    def rolling_returns(self, tickers: list[str], days: int = 30) -> pd.DataFrame:
        """
        Compute n-day price return for each ticker.
        Returns: DataFrame[ticker, start_price, end_price, return_pct]
        """
        tbl = self._pg_table("stock_prices")
        ticker_list = ", ".join(f"'{t}'" for t in tickers)
        since = (date.today() - timedelta(days=days + 5)).isoformat()

        sql = f"""
        WITH prices AS (
            SELECT ticker, time::DATE AS dt, close
            FROM {tbl}
            WHERE ticker IN ({ticker_list})
              AND time >= '{since}'
              AND close IS NOT NULL
        ),
        ranked AS (
            SELECT ticker, dt, close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY dt ASC)  AS rn_asc,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY dt DESC) AS rn_desc
            FROM prices
        ),
        endpoints AS (
            SELECT
                MAX(CASE WHEN rn_asc  = 1 THEN close END) AS start_price,
                MAX(CASE WHEN rn_desc = 1 THEN close END) AS end_price,
                ticker
            FROM ranked
            GROUP BY ticker
        )
        SELECT
            ticker,
            start_price,
            end_price,
            ROUND(((end_price - start_price) / NULLIF(start_price, 0)) * 100, 2) AS return_pct
        FROM endpoints
        WHERE start_price IS NOT NULL AND end_price IS NOT NULL
        ORDER BY return_pct DESC
        """
        return self._q(sql)

    def correlation_matrix(self, tickers: list[str], days: int = 90) -> pd.DataFrame:
        """
        Compute pairwise Pearson correlation of daily returns over `days` days.
        Returns wide-format DataFrame: rows=tickers, cols=tickers, values=correlation.
        """
        tbl = self._pg_table("stock_prices")
        ticker_list = ", ".join(f"'{t}'" for t in tickers)
        since = (date.today() - timedelta(days=days + 5)).isoformat()

        sql = f"""
        WITH daily AS (
            SELECT ticker, time::DATE AS dt, close
            FROM {tbl}
            WHERE ticker IN ({ticker_list})
              AND time >= '{since}'
              AND close IS NOT NULL
        ),
        returns AS (
            SELECT ticker, dt,
                   (close - LAG(close) OVER (PARTITION BY ticker ORDER BY dt))
                   / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY dt), 0) AS ret
            FROM daily
        ),
        pivoted AS (
            PIVOT returns ON ticker USING FIRST(ret) GROUP BY dt
        )
        SELECT * FROM pivoted ORDER BY dt
        """
        try:
            df = self._q(sql)
            if df.empty:
                return pd.DataFrame()
            df = df.drop(columns=["dt"], errors="ignore")
            return df.corr().round(3)
        except Exception as e:
            logger.warning("DuckDB correlation_matrix failed: %s", e)
            return pd.DataFrame()

    def factor_ranks(self, as_of_date: Optional[date] = None) -> pd.DataFrame:
        """
        Cross-sectional factor ranks from stock_technicals and company_financials.
        Returns: DataFrame[ticker, momentum_rank, rsi_rank, vol_rank, rs_rank]
        ranked 0–100 (100 = top percentile).
        """
        if as_of_date is None:
            as_of_date = date.today()

        tbl_tech = self._pg_table("stock_technicals")
        tbl_stocks = self._pg_table("stocks")

        sql = f"""
        WITH latest_tech AS (
            SELECT DISTINCT ON (ticker) ticker, date, rsi_14, vol_ratio,
                   rs_vs_spx, rs_vs_nsei, sma_20, sma_200, week_52_high, week_52_low
            FROM {tbl_tech}
            WHERE date <= '{as_of_date.isoformat()}'
            ORDER BY ticker, date DESC
        )
        SELECT
            t.ticker,
            t.date AS tech_date,
            t.rsi_14,
            t.vol_ratio,
            COALESCE(t.rs_vs_spx, t.rs_vs_nsei)     AS rs_rank_raw,
            PERCENT_RANK() OVER (ORDER BY t.rsi_14)  AS momentum_pct,
            PERCENT_RANK() OVER (ORDER BY t.vol_ratio) AS vol_pct,
            PERCENT_RANK() OVER (ORDER BY COALESCE(t.rs_vs_spx, t.rs_vs_nsei)) AS rs_pct,
            PERCENT_RANK() OVER (ORDER BY
                CASE WHEN t.week_52_high > 0
                     THEN (t.sma_20 - t.week_52_low) / NULLIF(t.week_52_high - t.week_52_low, 0)
                END
            ) AS price_pos_pct
        FROM latest_tech t
        JOIN {tbl_stocks} s ON s.ticker = t.ticker
        WHERE t.rsi_14 IS NOT NULL
        ORDER BY rs_pct DESC NULLS LAST
        """
        try:
            df = self._q(sql)
            # Convert to 0-100 scale
            for col in ["momentum_pct", "vol_pct", "rs_pct", "price_pos_pct"]:
                if col in df.columns:
                    df[col] = (df[col] * 100).round(1)
            df.rename(columns={
                "momentum_pct": "momentum_rank",
                "vol_pct":      "volume_rank",
                "rs_pct":       "rs_rank",
                "price_pos_pct": "price_position_rank",
            }, inplace=True)
            return df
        except Exception as e:
            logger.warning("DuckDB factor_ranks failed: %s", e)
            return pd.DataFrame()

    def sector_performance(self, days: int = 30) -> pd.DataFrame:
        """Average return by sector over `days` days."""
        tbl_prices = self._pg_table("stock_prices")
        tbl_stocks  = self._pg_table("stocks")
        since = (date.today() - timedelta(days=days + 5)).isoformat()

        sql = f"""
        WITH prices AS (
            SELECT p.ticker, p.time::DATE AS dt, p.close
            FROM {tbl_prices} p
            WHERE p.time >= '{since}' AND p.close IS NOT NULL
        ),
        endpoints AS (
            SELECT ticker,
                   FIRST_VALUE(close) OVER (PARTITION BY ticker ORDER BY dt ASC  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS start_p,
                   LAST_VALUE(close)  OVER (PARTITION BY ticker ORDER BY dt ASC  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS end_p
            FROM prices
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY dt DESC) = 1
        ),
        returns AS (
            SELECT e.ticker,
                   ((e.end_p - e.start_p) / NULLIF(e.start_p, 0)) * 100 AS ret_pct
            FROM endpoints e
        )
        SELECT
            s.sector,
            COUNT(*)           AS n_stocks,
            ROUND(AVG(r.ret_pct), 2) AS avg_return_pct,
            ROUND(MEDIAN(r.ret_pct), 2) AS median_return_pct
        FROM returns r
        JOIN {tbl_stocks} s ON s.ticker = r.ticker
        WHERE s.sector IS NOT NULL
        GROUP BY s.sector
        ORDER BY avg_return_pct DESC
        """
        try:
            return self._q(sql)
        except Exception as e:
            logger.warning("DuckDB sector_performance failed: %s", e)
            return pd.DataFrame()
