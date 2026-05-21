/**
 * CandlestickPanel — main institutional candlestick chart
 *
 * Features:
 * - OHLCV candlesticks + volume histogram
 * - Overlay toggles: SMA20/50/200, EMA9/21, Bollinger Bands
 * - AI signal markers (BUY▲ / SELL▼) from annotations API
 * - Price levels: entry (yellow dashed), stop (red dashed), target (green dashed)
 * - RSI sub-panel (separate chart, synced time scale)
 * - MACD sub-panel (separate chart, synced time scale)
 * - Drawing tools: horizontal line mode (click to draw), erase all
 * - Zoom in/out, fit content, pan left/right
 * - Crosshair OHLCV tooltip
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
    createChart, CrosshairMode, CandlestickSeries,
    HistogramSeries, LineSeries, LineStyle
} from 'lightweight-charts';
import { ZoomIn, ZoomOut, Maximize2, ChevronLeft, ChevronRight, Minus, Trash2, Target, TrendingUp } from 'lucide-react';

const OVERLAY_COLORS = {
    sma20:  '#3b82f6',   // blue
    sma50:  '#f59e0b',   // amber
    sma200: '#ef4444',   // red
    ema9:   '#06b6d4',   // cyan
    ema21:  '#a855f7',   // purple
    bb_upper: '#64748b', // slate
    bb_mid:   '#64748b',
    bb_lower: '#64748b',
};

export default function CandlestickPanel({ ticker, data, annotations, patternAnnotations }) {
    // data = { ohlcv, indicators, stats }
    // annotations = { markers, current_levels }
    // patternAnnotations = { markers: [{time, position, color, shape, text, size}, ...] }

    const [showPatterns, setShowPatterns] = useState(true);
    const [patternMarkers, setPatternMarkers] = useState([]);
    const [activeOverlays, setActiveOverlays] = useState({
        sma20: true, sma50: true, sma200: false,
        ema9: false, ema21: false,
        bb: false,
        volume: true,
        rsi: true,
        macd: false,
    });
    const [drawMode, setDrawMode] = useState(null); // null | 'hline' | 'erase'
    const [showLevels, setShowLevels] = useState(true);

    const mainRef = useRef(null);
    const rsiRef = useRef(null);
    const macdRef = useRef(null);
    const chartRef = useRef(null);
    const rsiChartRef = useRef(null);
    const macdChartRef = useRef(null);
    const seriesRefs = useRef({});
    const priceLineRefs = useRef([]);
    const drawnLinesRef = useRef([]);

    useEffect(() => {
        if (!mainRef.current || !data?.ohlcv?.length) return;

        // Cleanup previous instances
        [chartRef, rsiChartRef, macdChartRef].forEach(ref => {
            if (ref.current) { ref.current.remove(); ref.current = null; }
        });
        seriesRefs.current = {};
        priceLineRefs.current = [];
        drawnLinesRef.current = [];

        const CHART_OPTS = {
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: '#71717a',
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.04)' },
                horzLines: { color: 'rgba(255,255,255,0.04)' },
            },
            crosshair: { mode: CrosshairMode.Normal },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            timeScale: {
                borderColor: 'rgba(255,255,255,0.1)',
                timeVisible: true,
                secondsVisible: false,
            },
            autoSize: true,
        };

        // ── Main chart ─────────────────────────────────────────────────────
        const chart = createChart(mainRef.current, CHART_OPTS);
        chartRef.current = chart;

        // Candlestick series
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#22c55e', downColor: '#ef4444',
            borderVisible: false,
            wickUpColor: '#22c55e', wickDownColor: '#ef4444',
        });
        candleSeries.setData(data.ohlcv);
        seriesRefs.current.candle = candleSeries;

        // Volume series (overlay on main chart, bottom 20%)
        if (activeOverlays.volume) {
            const volSeries = chart.addSeries(HistogramSeries, {
                priceFormat: { type: 'volume' },
                priceScaleId: 'vol',
            });
            chart.priceScale('vol').applyOptions({
                scaleMargins: { top: 0.82, bottom: 0 },
            });
            const volData = data.ohlcv.map(d => ({
                time: d.time,
                value: d.volume,
                color: d.close >= d.open ? 'rgba(34,197,94,0.35)' : 'rgba(239,68,68,0.35)',
            }));
            volSeries.setData(volData);
            seriesRefs.current.volume = volSeries;
        }

        // Overlay indicators
        const ind = data.indicators || {};

        if (activeOverlays.sma20 && ind.sma20?.length) {
            const s = chart.addSeries(LineSeries, { color: OVERLAY_COLORS.sma20, lineWidth: 1, title: 'SMA20', crosshairMarkerVisible: false });
            s.setData(ind.sma20);
            seriesRefs.current.sma20 = s;
        }
        if (activeOverlays.sma50 && ind.sma50?.length) {
            const s = chart.addSeries(LineSeries, { color: OVERLAY_COLORS.sma50, lineWidth: 1, title: 'SMA50', crosshairMarkerVisible: false });
            s.setData(ind.sma50);
            seriesRefs.current.sma50 = s;
        }
        if (activeOverlays.sma200 && ind.sma200?.length) {
            const s = chart.addSeries(LineSeries, { color: OVERLAY_COLORS.sma200, lineWidth: 1, title: 'SMA200', crosshairMarkerVisible: false });
            s.setData(ind.sma200);
            seriesRefs.current.sma200 = s;
        }
        if (activeOverlays.ema9 && ind.ema9?.length) {
            const s = chart.addSeries(LineSeries, { color: OVERLAY_COLORS.ema9, lineWidth: 1, title: 'EMA9', crosshairMarkerVisible: false });
            s.setData(ind.ema9);
            seriesRefs.current.ema9 = s;
        }
        if (activeOverlays.ema21 && ind.ema21?.length) {
            const s = chart.addSeries(LineSeries, { color: OVERLAY_COLORS.ema21, lineWidth: 1, title: 'EMA21', crosshairMarkerVisible: false });
            s.setData(ind.ema21);
            seriesRefs.current.ema21 = s;
        }
        if (activeOverlays.bb && ind.bb_upper?.length) {
            [
                ['bb_upper', ind.bb_upper, 'BB+2σ'],
                ['bb_mid',   ind.bb_mid,   'BB Mid'],
                ['bb_lower', ind.bb_lower, 'BB-2σ'],
            ].forEach(([key, d, title]) => {
                const s = chart.addSeries(LineSeries, {
                    color: OVERLAY_COLORS[key], lineWidth: 1, title,
                    lineStyle: key === 'bb_mid' ? LineStyle.Dashed : LineStyle.Solid,
                    crosshairMarkerVisible: false,
                });
                s.setData(d);
                seriesRefs.current[key] = s;
            });
        }

        // AI Signal markers + pattern markers (merged and sorted by time)
        const aiMarkers = annotations?.markers || [];
        const pMarkers = (showPatterns && patternAnnotations?.markers) ? patternAnnotations.markers : [];
        const combinedMarkers = [...aiMarkers, ...pMarkers].sort((a, b) => {
            if (a.time < b.time) return -1;
            if (a.time > b.time) return 1;
            return 0;
        });
        if (combinedMarkers.length) {
            candleSeries.setMarkers(combinedMarkers);
        }

        // Price levels from latest AI signal
        if (showLevels && annotations?.current_levels) {
            const lvl = annotations.current_levels;
            if (lvl.entry) {
                const line = candleSeries.createPriceLine({
                    price: lvl.entry, color: '#fbbf24', lineWidth: 1,
                    lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Entry',
                });
                priceLineRefs.current.push(line);
            }
            if (lvl.stop) {
                const line = candleSeries.createPriceLine({
                    price: lvl.stop, color: '#ef4444', lineWidth: 1,
                    lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Stop',
                });
                priceLineRefs.current.push(line);
            }
            if (lvl.target) {
                const line = candleSeries.createPriceLine({
                    price: lvl.target, color: '#22c55e', lineWidth: 1,
                    lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Target',
                });
                priceLineRefs.current.push(line);
            }
        }

        chart.timeScale().fitContent();

        // ── RSI sub-chart ──────────────────────────────────────────────────
        if (activeOverlays.rsi && rsiRef.current && ind.rsi?.length) {
            const rsiChart = createChart(rsiRef.current, {
                ...CHART_OPTS,
                rightPriceScale: {
                    borderColor: 'rgba(255,255,255,0.1)',
                    scaleMargins: { top: 0.1, bottom: 0.1 },
                },
            });
            rsiChartRef.current = rsiChart;

            const rsiSeries = rsiChart.addSeries(LineSeries, {
                color: '#a855f7', lineWidth: 2, title: 'RSI 14',
            });
            rsiSeries.setData(ind.rsi);

            // Overbought/oversold reference lines
            rsiSeries.createPriceLine({ price: 70, color: '#ef4444', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '70' });
            rsiSeries.createPriceLine({ price: 30, color: '#22c55e', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '30' });
            rsiSeries.createPriceLine({ price: 50, color: '#64748b', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false });

            rsiChart.timeScale().fitContent();

            // Sync time scales
            chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range && rsiChartRef.current) rsiChartRef.current.timeScale().setVisibleLogicalRange(range);
            });
            rsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range && chartRef.current) chartRef.current.timeScale().setVisibleLogicalRange(range);
            });
        }

        // ── MACD sub-chart ─────────────────────────────────────────────────
        if (activeOverlays.macd && macdRef.current && ind.macd_line?.length) {
            const macdChart = createChart(macdRef.current, {
                ...CHART_OPTS,
                rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            });
            macdChartRef.current = macdChart;

            const macdLineSeries = macdChart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1, title: 'MACD' });
            const macdSigSeries = macdChart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, title: 'Signal' });
            const macdHistSeries = macdChart.addSeries(HistogramSeries, {
                title: 'Hist',
                priceScaleId: 'right',
            });

            macdLineSeries.setData(ind.macd_line);
            macdSigSeries.setData(ind.macd_signal);
            // Color histogram: green if positive, red if negative
            const histColored = (ind.macd_hist || []).map(d => ({
                ...d,
                color: d.value >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)',
            }));
            macdHistSeries.setData(histColored);

            macdChart.timeScale().fitContent();

            chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range && macdChartRef.current) macdChartRef.current.timeScale().setVisibleLogicalRange(range);
            });
            macdChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range && chartRef.current) chartRef.current.timeScale().setVisibleLogicalRange(range);
            });
        }

        // Cleanup
        return () => {
            [chartRef, rsiChartRef, macdChartRef].forEach(ref => {
                if (ref.current) { ref.current.remove(); ref.current = null; }
            });
        };
    }, [data, annotations, patternAnnotations, activeOverlays, showLevels, showPatterns]);

    // Drawing tools handler
    useEffect(() => {
        if (!chartRef.current || !mainRef.current) return;

        const handleClick = (param) => {
            if (drawMode !== 'hline' || !param.point) return;
            const candleSeries = seriesRefs.current.candle;
            if (!candleSeries) return;
            const price = chartRef.current.priceScale('right').coordinateToPrice(param.point.y);
            if (price == null) return;
            const line = candleSeries.createPriceLine({
                price,
                color: '#fbbf24',
                lineWidth: 1,
                lineStyle: LineStyle.Solid,
                axisLabelVisible: true,
                title: `${price.toFixed(2)}`,
            });
            drawnLinesRef.current.push(line);
        };

        chartRef.current.subscribeClick(handleClick);
        return () => {
            if (chartRef.current) chartRef.current.unsubscribeClick(handleClick);
        };
    }, [drawMode]);

    const zoomIn = () => {
        const ts = chartRef.current?.timeScale();
        if (!ts) return;
        const r = ts.getVisibleLogicalRange();
        if (r) ts.setVisibleLogicalRange({ from: r.from + (r.to-r.from)*0.15, to: r.to - (r.to-r.from)*0.15 });
    };
    const zoomOut = () => {
        const ts = chartRef.current?.timeScale();
        if (!ts) return;
        const r = ts.getVisibleLogicalRange();
        if (r) ts.setVisibleLogicalRange({ from: r.from - (r.to-r.from)*0.2, to: r.to + (r.to-r.from)*0.2 });
    };
    const fitAll = () => chartRef.current?.timeScale().fitContent();
    const panLeft = () => {
        const ts = chartRef.current?.timeScale();
        if (!ts) return;
        const r = ts.getVisibleLogicalRange();
        if (r) { const d = (r.to-r.from)*0.2; ts.setVisibleLogicalRange({ from: r.from-d, to: r.to-d }); }
    };
    const panRight = () => {
        const ts = chartRef.current?.timeScale();
        if (!ts) return;
        const r = ts.getVisibleLogicalRange();
        if (r) { const d = (r.to-r.from)*0.2; ts.setVisibleLogicalRange({ from: r.from+d, to: r.to+d }); }
    };
    const eraseDrawings = () => {
        const candleSeries = seriesRefs.current.candle;
        if (!candleSeries) return;
        drawnLinesRef.current.forEach(line => { try { candleSeries.removePriceLine(line); } catch {} });
        drawnLinesRef.current = [];
        setDrawMode(null);
    };

    const stats = data?.stats || {};
    const isUp = (stats.change_pct || 0) >= 0;

    return (
        <div className="flex flex-col h-full gap-1">
            {/* Stats bar */}
            <div className="flex items-center gap-4 px-2 py-1 text-xs text-zinc-400 flex-wrap">
                <span className="text-zinc-100 font-semibold text-sm">{ticker}</span>
                <span className="text-zinc-100 font-mono">{stats.current_price?.toFixed(2)}</span>
                <span className={isUp ? 'text-green-400' : 'text-red-400'}>
                    {isUp ? '+' : ''}{stats.change?.toFixed(2)} ({isUp ? '+' : ''}{stats.change_pct?.toFixed(2)}%)
                </span>
                <span>H: {stats.high?.toFixed(2)}</span>
                <span>L: {stats.low?.toFixed(2)}</span>
                <span>Vol: {stats.volume?.toLocaleString()}</span>
                <span>52W: {stats.week_52_low?.toFixed(2)} – {stats.week_52_high?.toFixed(2)}</span>
            </div>

            {/* Toolbar: overlays + drawing */}
            <div className="flex items-center gap-1 px-2 flex-wrap">
                {/* Overlay toggles */}
                {[
                    ['sma20', 'SMA20', OVERLAY_COLORS.sma20],
                    ['sma50', 'SMA50', OVERLAY_COLORS.sma50],
                    ['sma200', 'SMA200', OVERLAY_COLORS.sma200],
                    ['ema9', 'EMA9', OVERLAY_COLORS.ema9],
                    ['ema21', 'EMA21', OVERLAY_COLORS.ema21],
                    ['bb', 'BB', OVERLAY_COLORS.bb_upper],
                    ['volume', 'Vol', '#64748b'],
                    ['rsi', 'RSI', '#a855f7'],
                    ['macd', 'MACD', '#3b82f6'],
                ].map(([key, label, color]) => (
                    <button
                        key={key}
                        onClick={() => setActiveOverlays(p => ({ ...p, [key]: !p[key] }))}
                        className={`px-2 py-0.5 rounded text-xs font-mono border transition-all ${
                            activeOverlays[key]
                                ? 'border-transparent text-zinc-900 font-semibold'
                                : 'border-zinc-700 text-zinc-500 hover:border-zinc-500'
                        }`}
                        style={activeOverlays[key] ? { background: color } : {}}
                    >{label}</button>
                ))}

                {/* Pattern markers toggle */}
                <button
                    onClick={() => setShowPatterns(p => !p)}
                    className={`px-2 py-0.5 rounded text-xs font-mono border transition-all ${
                        showPatterns
                            ? 'border-transparent text-zinc-900 font-semibold'
                            : 'border-zinc-700 text-zinc-500 hover:border-zinc-500'
                    }`}
                    style={showPatterns ? { background: '#f59e0b' } : {}}
                    title="Toggle pattern markers"
                >Patterns</button>

                <div className="w-px h-4 bg-zinc-700 mx-1" />

                {/* Drawing tools */}
                <button
                    onClick={() => setDrawMode(drawMode === 'hline' ? null : 'hline')}
                    className={`p-1 rounded text-xs ${drawMode === 'hline' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/40' : 'text-zinc-500 hover:text-zinc-300'}`}
                    title="Draw horizontal line"
                ><Minus size={14} /></button>
                <button
                    onClick={eraseDrawings}
                    className="p-1 rounded text-xs text-zinc-500 hover:text-red-400"
                    title="Erase drawn lines"
                ><Trash2 size={14} /></button>
                <button
                    onClick={() => setShowLevels(p => !p)}
                    className={`p-1 rounded text-xs ${showLevels ? 'text-yellow-400' : 'text-zinc-500 hover:text-zinc-300'}`}
                    title="Toggle entry/stop/target levels"
                ><Target size={14} /></button>

                <div className="w-px h-4 bg-zinc-700 mx-1" />

                {/* Navigation */}
                <button onClick={zoomIn}  className="p-1 text-zinc-500 hover:text-zinc-300"><ZoomIn size={14} /></button>
                <button onClick={zoomOut} className="p-1 text-zinc-500 hover:text-zinc-300"><ZoomOut size={14} /></button>
                <button onClick={fitAll}  className="p-1 text-zinc-500 hover:text-zinc-300"><Maximize2 size={14} /></button>
                <button onClick={panLeft} className="p-1 text-zinc-500 hover:text-zinc-300"><ChevronLeft size={14} /></button>
                <button onClick={panRight} className="p-1 text-zinc-500 hover:text-zinc-300"><ChevronRight size={14} /></button>

                {drawMode === 'hline' && (
                    <span className="text-xs text-yellow-400 ml-2">Click on chart to draw horizontal line</span>
                )}
            </div>

            {/* Main chart */}
            <div ref={mainRef} className="flex-1 min-h-0 rounded" style={{ cursor: drawMode ? 'crosshair' : 'default' }} />

            {/* Pattern legend */}
            {showPatterns && patternAnnotations?.markers?.length > 0 && (() => {
                const sorted = [...patternAnnotations.markers].sort((a, b) => (a.time < b.time ? 1 : -1));
                const recent = sorted.slice(0, 3);
                const now = Date.now();
                const fmt = (time) => {
                    // time can be a unix timestamp (seconds) or YYYY-MM-DD string
                    let ms;
                    if (typeof time === 'string') {
                        ms = new Date(time).getTime();
                    } else {
                        ms = time * 1000;
                    }
                    const diff = Math.floor((now - ms) / 86400000);
                    if (diff === 0) return 'Today';
                    if (diff === 1) return 'Yesterday';
                    if (diff < 7) return `${diff} days ago`;
                    if (diff < 14) return '1 week ago';
                    return `${Math.floor(diff / 7)} weeks ago`;
                };
                return (
                    <div className="flex items-center gap-2 px-2 py-1 flex-wrap">
                        <span className="text-xs text-zinc-600 shrink-0">Patterns:</span>
                        {recent.map((m, i) => (
                            <span key={i}
                                className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border border-zinc-700 bg-zinc-800/60"
                            >
                                <span style={{ color: m.color || '#f59e0b' }}>◈</span>
                                <span className="text-zinc-300">{m.text || 'Pattern'}</span>
                                <span className="text-zinc-600">({fmt(m.time)})</span>
                            </span>
                        ))}
                    </div>
                );
            })()}

            {/* RSI sub-panel */}
            {activeOverlays.rsi && (
                <div className="relative" style={{ height: '120px' }}>
                    <span className="absolute top-1 left-2 text-xs text-zinc-500 z-10 pointer-events-none">RSI 14</span>
                    <div ref={rsiRef} className="w-full h-full" />
                </div>
            )}

            {/* MACD sub-panel */}
            {activeOverlays.macd && (
                <div className="relative" style={{ height: '120px' }}>
                    <span className="absolute top-1 left-2 text-xs text-zinc-500 z-10 pointer-events-none">MACD (12,26,9)</span>
                    <div ref={macdRef} className="w-full h-full" />
                </div>
            )}
        </div>
    );
}
