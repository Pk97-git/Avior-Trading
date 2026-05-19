/**
 * hooks/useLivePrices.js
 * ======================
 * useLivePrices(tickers: string[])
 *   → { prices: { [ticker]: { price, change_pct, ts } } }
 *
 * Opens an SSE connection to /api/v1/prices/stream?tickers=AAPL,MSFT,...
 * Reconnects automatically when the stream ends (server closes after 5 min).
 * Cleans up EventSource and any pending reconnect timeout on unmount.
 */
import { useEffect, useRef, useState } from 'react';

const SSE_BASE_URL    = '/api/v1/prices/stream';
const RECONNECT_DELAY = 5000; // ms — wait 5 s before reconnecting

/**
 * @param {string[]} tickers  Array of ticker symbols, e.g. ['AAPL', 'MSFT']
 * @returns {{ prices: Object.<string, { price: number, change_pct: number, ts: string }> }}
 */
export function useLivePrices(tickers) {
  const [prices, setPrices] = useState({});

  // Stable refs so we can clean up from the effect's cleanup function
  const esRef      = useRef(null);   // active EventSource
  const timerRef   = useRef(null);   // pending reconnect timeout
  const mountedRef = useRef(true);   // tracks whether component is mounted

  useEffect(() => {
    mountedRef.current = true;

    if (!tickers || tickers.length === 0) {
      return;
    }

    const connect = () => {
      if (!mountedRef.current) return;

      // Build query string from provided tickers
      const url = `${SSE_BASE_URL}?tickers=${encodeURIComponent(tickers.join(','))}`;

      const es = new EventSource(url);
      esRef.current = es;

      // ── Incoming price data ────────────────────────────────────────────────
      es.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(event.data);
          if (data && data.ticker) {
            setPrices((prev) => ({
              ...prev,
              [data.ticker]: {
                price:      data.price,
                change_pct: data.change_pct,
                ts:         data.ts,
              },
            }));
          }
        } catch {
          // Malformed JSON — ignore silently
        }
      };

      // ── Server signals normal stream end (reconnect) ───────────────────────
      es.addEventListener('end', () => {
        es.close();
        esRef.current = null;
        scheduleReconnect();
      });

      // ── Network / server error — reconnect after delay ─────────────────────
      es.onerror = () => {
        es.close();
        esRef.current = null;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (!mountedRef.current) return;
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, RECONNECT_DELAY);
    };

    connect();

    // ── Cleanup on unmount or tickers change ──────────────────────────────────
    return () => {
      mountedRef.current = false;

      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }

      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [tickers.join(',')]); // re-run only when the ticker list actually changes

  return { prices };
}
