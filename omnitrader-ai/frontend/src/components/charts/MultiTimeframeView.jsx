import React, { useEffect, useRef } from 'react';
import { createChart, CrosshairMode, CandlestickSeries, HistogramSeries } from 'lightweight-charts';

function MiniChart({ label, bars }) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);

    useEffect(() => {
        if (!containerRef.current || !bars?.length) return;
        if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }

        const chart = createChart(containerRef.current, {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#71717a' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
            crosshair: { mode: CrosshairMode.Normal },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)', minimumWidth: 50 },
            timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: true, secondsVisible: false },
            autoSize: true,
        });
        chartRef.current = chart;

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#22c55e', downColor: '#ef4444',
            borderVisible: false,
            wickUpColor: '#22c55e', wickDownColor: '#ef4444',
        });
        candleSeries.setData(bars);

        const volSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'vol',
        });
        chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
        volSeries.setData(bars.map(d => ({
            time: d.time, value: d.volume,
            color: d.close >= d.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
        })));

        chart.timeScale().fitContent();

        return () => { if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; } };
    }, [bars]);

    const lastBar = bars?.[bars.length - 1];
    const prevBar = bars?.[bars.length - 2];
    const chg = lastBar && prevBar ? ((lastBar.close - prevBar.close) / prevBar.close * 100) : 0;
    const isUp = chg >= 0;

    return (
        <div className="flex flex-col bg-zinc-900 rounded-lg border border-zinc-800 overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
                <span className="text-xs font-semibold text-zinc-300">{label}</span>
                {lastBar && (
                    <div className="flex items-center gap-2 text-xs font-mono">
                        <span className="text-zinc-200">{lastBar.close?.toFixed(2)}</span>
                        <span className={isUp ? 'text-green-400' : 'text-red-400'}>
                            {isUp ? '+' : ''}{chg.toFixed(2)}%
                        </span>
                    </div>
                )}
            </div>
            <div ref={containerRef} className="flex-1" style={{ minHeight: '200px' }} />
        </div>
    );
}

export default function MultiTimeframeView({ ticker, multiData }) {
    // multiData = { timeframes: { '1D': [...], '1W': [...], '1M': [...] } }
    const tfs = multiData?.timeframes || {};

    return (
        <div className="h-full p-3 overflow-auto">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 h-full">
                {['1D', '1W', '1M'].map(tf => (
                    <MiniChart key={tf} label={`${ticker} · ${tf}`} bars={tfs[tf] || []} />
                ))}
            </div>
        </div>
    );
}
