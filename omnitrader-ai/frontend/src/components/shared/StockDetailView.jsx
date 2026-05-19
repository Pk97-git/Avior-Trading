import React, { useEffect, useState, useMemo, useRef } from 'react';
import { ingestionApi, agentsApi } from '../../api';
import { Loader2, X, TrendingUp, TrendingDown, Clock, BarChart2, FileText, Share2, Maximize2, Minimize2, Activity, ZoomIn, ZoomOut, MoveLeft, MoveRight, RefreshCcw, Briefcase, Globe, Cpu } from 'lucide-react';
import { createChart, CrosshairMode, CandlestickSeries, HistogramSeries } from 'lightweight-charts';

export default function StockDetailView({ ticker, onClose }) {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState({ prices: [], fundamentals: [], sentiment: [], promoter: [], aiAnalysis: null });
    const [timeRange, setTimeRange] = useState('1Y'); // 1M, 3M, 6M, 1Y, 5Y, MAX
    const [isFullscreen, setIsFullscreen] = useState(true);
    const [activeTab, setActiveTab] = useState('chart'); // chart, fundamentals, institutional, macro, sentiment, ai
    const [finStmtTab, setFinStmtTab] = useState('income_statement'); // Sub-tab for fundamentals

    const chartContainerRef = useRef(null);
    const chartRef = useRef(null);

    useEffect(() => {
        const load = async () => {
            setLoading(true);
            try {
                // Fetch max data to allow client-side filtering by timeRange
                const [pRes, fRes, sRes, promRes, aiRes] = await Promise.all([
                    ingestionApi.getPrices(ticker, null, 5000), // get max available
                    ingestionApi.getFundamentals(ticker),
                    ingestionApi.getSentiment(ticker),
                    ingestionApi.getPromoter(ticker),
                    agentsApi.getAnalysis(ticker).catch(() => ({ data: null }))
                ]);

                // Backend returns descending (newest first), we need ascending for charts
                const prices = (pRes.data || []).reverse();

                setData({
                    prices,
                    fundamentals: fRes.data || [],
                    sentiment: sRes.data || [],
                    promoter: promRes?.data || [],
                    aiAnalysis: aiRes?.data || null
                });
            } catch (err) {
                console.error("Failed to load details:", err);
            } finally {
                setLoading(false);
            }
        };
        if (ticker) load();
    }, [ticker]);

    // Keyboard shortcut for escape to close
    useEffect(() => {
        const handleEsc = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', handleEsc);
        return () => window.removeEventListener('keydown', handleEsc);
    }, [onClose]);

    // Format data for TradingView Lightweight Charts
    const tvData = useMemo(() => {
        if (!data.prices.length) return { candleData: [], volumeData: [] };

        const now = new Date();
        let cutoff = new Date();

        switch (timeRange) {
            case '1M': cutoff.setMonth(now.getMonth() - 1); break;
            case '3M': cutoff.setMonth(now.getMonth() - 3); break;
            case '6M': cutoff.setMonth(now.getMonth() - 6); break;
            case '1Y': cutoff.setFullYear(now.getFullYear() - 1); break;
            case '5Y': cutoff.setFullYear(now.getFullYear() - 5); break;
            case 'MAX': cutoff = new Date(0); break;
            default: cutoff.setFullYear(now.getFullYear() - 1);
        }

        const cutoffIso = cutoff.toISOString().split('T')[0];
        const filtered = data.prices.filter(p => p.time.split('T')[0] >= cutoffIso);

        const candleData = filtered.map(p => ({
            time: p.time.split('T')[0], // TV requires YYYY-MM-DD
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close
        }));

        const volumeData = filtered.map(p => ({
            time: p.time.split('T')[0],
            value: p.volume || 0, // Fallback for days with null volume from Yahoo Finance
            color: p.close >= p.open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)' // emerald or red
        }));

        return { candleData, volumeData };
    }, [data.prices, timeRange]);

    // Render TradingView Chart
    useEffect(() => {
        if (!chartContainerRef.current || activeTab !== 'chart' || loading || tvData.candleData.length === 0) return;

        // Cleanup previous instance
        if (chartRef.current) {
            chartRef.current.remove();
        }

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: '#71717a', // zinc-500
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    width: 1,
                    color: 'rgba(255, 255, 255, 0.2)',
                    style: 1, // Dotted
                },
                horzLine: {
                    width: 1,
                    color: 'rgba(255, 255, 255, 0.2)',
                    style: 1, // Dotted
                },
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                autoScale: true,
            },
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                timeVisible: true,
                secondsVisible: false,
                fixLeftEdge: true,
                fixRightEdge: true,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: true,
            },
            handleScale: {
                axisPressedMouseMove: true,
                mouseWheel: true,
                pinch: true,
            },
            autoSize: true, // Auto resize with container
        });

        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#10b981', // emerald-500
            downColor: '#ef4444', // red-500
            borderVisible: false,
            wickUpColor: '#10b981',
            wickDownColor: '#ef4444',
        });
        candlestickSeries.setData(tvData.candleData);

        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: '#26a69a',
            priceFormat: { type: 'volume' },
            priceScaleId: '', // set as an overlay
            scaleMargins: {
                top: 0.8, // volume takes bottom 20%
                bottom: 0,
            },
        });
        volumeSeries.setData(tvData.volumeData);

        chart.timeScale().fitContent();

        chartRef.current = chart;

        // Custom Resize handler just in case
        const resizeObserver = new ResizeObserver(entries => {
            if (entries.length === 0 || entries[0].target !== chartContainerRef.current) return;
            const newRect = entries[0].contentRect;
            chart.applyOptions({ width: newRect.width, height: newRect.height });
        });
        resizeObserver.observe(chartContainerRef.current);

        return () => {
            resizeObserver.disconnect();
            if (chartRef.current) {
                chartRef.current.remove();
                chartRef.current = null;
            }
        };
    }, [tvData, activeTab, loading]);

    // Computations for header stats
    const latestPrice = data.prices.length ? data.prices[data.prices.length - 1] : null;
    const previousPrice = data.prices.length > 1 ? data.prices[data.prices.length - 2] : null;

    let change = 0, changePct = 0;
    if (latestPrice && previousPrice) {
        change = latestPrice.close - previousPrice.close;
        changePct = (change / previousPrice.close) * 100;
    }

    const isPositive = change >= 0;

    // Chart Navigation Controls
    const handleZoomIn = () => {
        if (!chartRef.current) return;
        const timeScale = chartRef.current.timeScale();
        const currentRange = timeScale.getVisibleLogicalRange();
        if (currentRange) {
            const zoomAmount = (currentRange.to - currentRange.from) * 0.2;
            timeScale.setVisibleLogicalRange({
                from: currentRange.from + zoomAmount,
                to: currentRange.to - zoomAmount,
            });
        }
    };

    const handleZoomOut = () => {
        if (!chartRef.current) return;
        const timeScale = chartRef.current.timeScale();
        const currentRange = timeScale.getVisibleLogicalRange();
        if (currentRange) {
            const zoomAmount = (currentRange.to - currentRange.from) * 0.2;
            timeScale.setVisibleLogicalRange({
                from: currentRange.from - zoomAmount,
                to: currentRange.to + zoomAmount,
            });
        }
    };

    const handlePanLeft = () => {
        if (!chartRef.current) return;
        const timeScale = chartRef.current.timeScale();
        const currentRange = timeScale.getVisibleLogicalRange();
        if (currentRange) {
            const panAmount = (currentRange.to - currentRange.from) * 0.2;
            timeScale.setVisibleLogicalRange({
                from: currentRange.from - panAmount,
                to: currentRange.to - panAmount,
            });
        }
    };

    const handlePanRight = () => {
        if (!chartRef.current) return;
        const timeScale = chartRef.current.timeScale();
        const currentRange = timeScale.getVisibleLogicalRange();
        if (currentRange) {
            const panAmount = (currentRange.to - currentRange.from) * 0.2;
            timeScale.setVisibleLogicalRange({
                from: currentRange.from + panAmount,
                to: currentRange.to + panAmount,
            });
        }
    };

    const handleReset = () => {
        if (!chartRef.current) return;
        chartRef.current.timeScale().fitContent();
    };

    if (!ticker) return null;

    return (
        <div className={`fixed z-50 bg-background/95 backdrop-blur-sm transition-all duration-300 ease-in-out flex flex-col
            ${isFullscreen ? 'inset-0' : 'inset-4 md:inset-10 lg:inset-x-20 rounded-xl shadow-2xl border border-border/50'}
        `}>
            {/* Header / Top Bar */}
            <div className="flex-none h-20 border-b border-border bg-card px-6 flex items-center justify-between shrink-0 rounded-t-xl">
                <div className="flex items-center gap-6">
                    <div>
                        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground to-muted-foreground bg-clip-text text-transparent">
                            {ticker}
                        </h1>
                        <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider flex items-center gap-1.5 mt-0.5">
                            <Activity className="w-3 h-3" /> OmniTrader Professional
                        </p>
                    </div>

                    <div className="w-px h-10 bg-border mx-2" />

                    {/* Live Quotes Area */}
                    {!loading && latestPrice && (
                        <div className="flex flex-col">
                            <div className="flex items-baseline gap-3">
                                <span className="text-3xl font-mono font-bold tracking-tight">
                                    {latestPrice.close.toFixed(2)}
                                </span>
                                <span className={`flex items-center text-sm font-semibold px-2 py-0.5 rounded-full ${isPositive ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'}`}>
                                    {isPositive ? <TrendingUp className="w-3.5 h-3.5 mr-1" /> : <TrendingDown className="w-3.5 h-3.5 mr-1" />}
                                    {change > 0 ? '+' : ''}{change.toFixed(2)} ({changePct.toFixed(2)}%)
                                </span>
                            </div>
                            <span className="text-xs text-muted-foreground font-mono mt-1 flex items-center gap-1">
                                <Clock className="w-3 h-3" /> Last updated: {new Date(latestPrice.time).toLocaleDateString()}
                            </span>
                        </div>
                    )}
                </div>

                <div className="flex items-center gap-3">
                    {/* Time Range Selectors */}
                    <div className="hidden md:flex bg-muted/50 p-1 rounded-lg border border-border/50">
                        {['1M', '3M', '6M', '1Y', '5Y', 'MAX'].map(r => (
                            <button
                                key={r}
                                onClick={() => setTimeRange(r)}
                                className={`px-4 py-1.5 text-xs font-semibold rounded-md transition-all ${timeRange === r ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                {r}
                            </button>
                        ))}
                    </div>
                    <div className="w-px h-6 bg-border mx-2" />
                    <button onClick={() => setIsFullscreen(!isFullscreen)} className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors">
                        {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                    </button>
                    <button onClick={onClose} className="p-2 text-muted-foreground hover:text-red-500 hover:bg-red-500/10 rounded-md transition-colors">
                        <X className="w-5 h-5" />
                    </button>
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex overflow-hidden">
                {/* Left Sidebar (Nav) */}
                <div className="w-16 border-r border-border bg-muted/10 flex flex-col items-center py-4 gap-4 shrink-0 overflow-y-auto">
                    <button onClick={() => setActiveTab('chart')} className={`p-3 rounded-lg transition-colors ${activeTab === 'chart' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-muted'}`} title="Advanced Chart">
                        <BarChart2 className="w-5 h-5" />
                    </button>
                    <button onClick={() => setActiveTab('fundamentals')} className={`p-3 rounded-lg transition-colors ${activeTab === 'fundamentals' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-muted'}`} title="Fundamentals">
                        <FileText className="w-5 h-5" />
                    </button>
                    <button onClick={() => setActiveTab('ownership')} className={`p-3 rounded-lg transition-colors ${activeTab === 'ownership' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-muted'}`} title="Shareholding Pattern / Ownership">
                        <Briefcase className="w-5 h-5" />
                    </button>
                    <button onClick={() => setActiveTab('sentiment')} className={`p-3 rounded-lg transition-colors ${activeTab === 'sentiment' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-muted'}`} title="Sentiment & News">
                        <Share2 className="w-5 h-5" />
                    </button>
                    <div className="flex-1" />
                    <button onClick={() => setActiveTab('ai')} className={`p-3 rounded-lg transition-colors mb-4 ${activeTab === 'ai' ? 'bg-purple-500/20 text-purple-500' : 'text-muted-foreground hover:bg-muted'}`} title="AI Embeddings & Engine Data">
                        <Cpu className="w-5 h-5" />
                    </button>
                </div>

                {/* Main View */}
                <div className="flex-1 bg-background relative flex flex-col min-w-0">
                    {loading && (
                        <div className="absolute inset-0 z-10 bg-background/80 backdrop-blur-sm flex items-center justify-center">
                            <div className="flex flex-col items-center gap-3">
                                <Loader2 className="w-8 h-8 animate-spin text-primary" />
                                <p className="text-sm font-medium text-muted-foreground animate-pulse">Loading market data...</p>
                            </div>
                        </div>
                    )}

                    {!loading && activeTab === 'chart' && (
                        <div className="flex-1 relative pointer-events-auto">
                            {/* Floating Chart Navigation Toolbar */}
                            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1 bg-background/80 backdrop-blur-md p-1.5 rounded-lg border border-border shadow-lg">
                                <button onClick={handlePanLeft} className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Pan Left">
                                    <MoveLeft className="w-4 h-4" />
                                </button>
                                <button onClick={handleZoomIn} className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Zoom In">
                                    <ZoomIn className="w-4 h-4" />
                                </button>
                                <button onClick={handleReset} className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Reset View">
                                    <RefreshCcw className="w-4 h-4" />
                                </button>
                                <button onClick={handleZoomOut} className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Zoom Out">
                                    <ZoomOut className="w-4 h-4" />
                                </button>
                                <button onClick={handlePanRight} className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors" title="Pan Right">
                                    <MoveRight className="w-4 h-4" />
                                </button>
                            </div>

                            {/* TradingView Container - Must be absolute to avoid Flex bugs with canvas event tracking */}
                            <div
                                ref={chartContainerRef}
                                className="absolute inset-0 touch-none"
                            />
                        </div>
                    )}

                    {!loading && activeTab === 'fundamentals' && (
                        <div className="flex-1 p-8 overflow-y-auto w-full">
                            <h2 className="text-xl font-bold mb-6">Financial Statements & Metrics</h2>
                            {data.fundamentals.length === 0 ? (
                                <div className="text-muted-foreground p-12 text-center border border-dashed border-border rounded-xl w-full">
                                    No fundamental data exists for this ticker yet.
                                </div>
                            ) : (
                                <div className="space-y-8">
                                    {/* Calculated Core Metrics (Most Recent Period) */}
                                    <div className="bg-card border border-border p-6 rounded-xl shadow-sm">
                                        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-4">Latest Calculated Metrics (Annual)</h3>
                                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                                            <div>
                                                <p className="text-xs text-muted-foreground mb-1">Operating Margin</p>
                                                <p className="text-xl font-bold font-mono text-emerald-500">
                                                    {data.fundamentals[0].operating_margin ? (data.fundamentals[0].operating_margin * 100).toFixed(2) + '%' : '—'}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs text-muted-foreground mb-1">Return on Equity (ROE)</p>
                                                <p className="text-xl font-bold font-mono">
                                                    {data.fundamentals[0].roe ? (data.fundamentals[0].roe * 100).toFixed(2) + '%' : '—'}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs text-muted-foreground mb-1">Return on Invested Capital (ROIC)</p>
                                                <p className="text-xl font-bold font-mono">
                                                    {data.fundamentals[0].roic ? (data.fundamentals[0].roic * 100).toFixed(2) + '%' : '—'}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs text-muted-foreground mb-1">Free Cash Flow</p>
                                                <p className="text-xl font-bold font-mono">
                                                    {data.fundamentals[0].free_cash_flow ? '$' + (data.fundamentals[0].free_cash_flow / 1e9).toFixed(2) + 'B' : '—'}
                                                </p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Document Explorer */}
                                    <div className="border border-border rounded-xl bg-card overflow-hidden">
                                        <div className="flex border-b border-border bg-muted/20">
                                            {['income_statement', 'balance_sheet', 'cash_flow'].map((docType) => (
                                                <button
                                                    key={docType}
                                                    onClick={() => setFinStmtTab(docType)}
                                                    className={`px-6 py-3 text-sm font-semibold transition-colors flex-1 text-center ${finStmtTab === docType ? 'bg-background border-b-2 border-primary text-foreground' : 'text-muted-foreground hover:bg-muted/50'}`}
                                                >
                                                    {docType.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}
                                                </button>
                                            ))}
                                        </div>

                                        <div className="p-0 overflow-x-auto">
                                            <table className="w-full text-left text-sm">
                                                <thead className="bg-muted/30 border-b border-border">
                                                    <tr>
                                                        <th className="px-6 py-4 font-semibold text-muted-foreground break-words w-1/3">Line Item</th>
                                                        {/* Render headers for the available years */}
                                                        {data.fundamentals.map((f, i) => (
                                                            <th key={i} className="px-6 py-4 font-semibold text-muted-foreground text-right w-1/6">
                                                                {f.report_period || new Date(f.fiscal_date).getFullYear()}
                                                            </th>
                                                        ))}
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-border">
                                                    {/* We use the keys of the most recent document to generate the rows */}
                                                    {data.fundamentals[0][finStmtTab] && Object.keys(data.fundamentals[0][finStmtTab]).map((key) => (
                                                        <tr key={key} className="hover:bg-muted/10 transition-colors">
                                                            <td className="px-6 py-3 font-medium text-foreground">{key}</td>
                                                            {data.fundamentals.map((f, i) => (
                                                                <td key={i} className="px-6 py-3 text-right font-mono text-muted-foreground">
                                                                    {f[finStmtTab] && f[finStmtTab][key] !== null
                                                                        ? (typeof f[finStmtTab][key] === 'number' && f[finStmtTab][key] > 10000
                                                                            ? (f[finStmtTab][key] / 1e9).toFixed(2) + 'B'
                                                                            : f[finStmtTab][key])
                                                                        : '—'
                                                                    }
                                                                </td>
                                                            ))}
                                                        </tr>
                                                    ))}
                                                    {!data.fundamentals[0][finStmtTab] && (
                                                        <tr>
                                                            <td colSpan={data.fundamentals.length + 1} className="px-6 py-8 text-center text-muted-foreground italic">
                                                                Raw document not available for this period. Run ingestion update.
                                                            </td>
                                                        </tr>
                                                    )}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {!loading && activeTab === 'sentiment' && (
                        <div className="flex-1 p-8 overflow-y-auto w-full">
                            <h2 className="text-xl font-bold mb-6">News & Sentiment History</h2>
                            {data.sentiment.length === 0 ? (
                                <div className="text-muted-foreground p-12 text-center border border-dashed border-border rounded-xl w-full">
                                    No sentiment data exists for this ticker yet.
                                </div>
                            ) : (
                                <div className="overflow-x-auto border border-border rounded-xl bg-card w-full">
                                    <table className="w-full text-left">
                                        <thead className="bg-muted/30 border-b border-border">
                                            <tr>
                                                <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Time</th>
                                                <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Source</th>
                                                <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Headline</th>
                                                <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground text-right">Score</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-border text-sm">
                                            {data.sentiment.map((s, i) => (
                                                <tr key={i} className="hover:bg-muted/10 transition-colors">
                                                    <td className="px-6 py-4 whitespace-nowrap text-muted-foreground">{new Date(s.time).toLocaleString()}</td>
                                                    <td className="px-6 py-4 font-medium"><span className="bg-muted px-2 py-1 rounded text-xs">{s.source}</span></td>
                                                    <td className="px-6 py-4">
                                                        <a href={s.url} target="_blank" rel="noopener noreferrer" className="hover:underline hover:text-primary transition-colors">{s.headline}</a>
                                                    </td>
                                                    <td className={`px-6 py-4 text-right font-bold ${s.sentiment_score > 0 ? 'text-emerald-500' : s.sentiment_score < 0 ? 'text-red-500' : 'text-muted-foreground'}`}>
                                                        {s.sentiment_score?.toFixed(2) || '0.00'}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    )}

                    {!loading && activeTab === 'ownership' && (
                        <div className="flex-1 p-8 overflow-y-auto w-full">
                            <h2 className="text-xl font-bold mb-6">Shareholding Pattern</h2>
                            {data.promoter && data.promoter.length > 0 ? (
                                <div className="overflow-x-auto border border-border rounded-xl bg-card w-full">
                                    <table className="w-full text-left text-sm">
                                        <thead className="bg-muted/30 border-b border-border">
                                            <tr>
                                                <th className="px-6 py-4 font-semibold text-muted-foreground">Quarter End</th>
                                                <th className="px-6 py-4 font-semibold text-muted-foreground text-right">Promoter %</th>
                                                <th className="px-6 py-4 font-semibold text-muted-foreground text-right">FII %</th>
                                                <th className="px-6 py-4 font-semibold text-muted-foreground text-right">DII %</th>
                                                <th className="px-6 py-4 font-semibold text-muted-foreground text-right">Public %</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-border">
                                            {data.promoter.map((p, i) => (
                                                <tr key={i} className="hover:bg-muted/10">
                                                    <td className="px-6 py-4 font-medium">{p.quarter_end ? new Date(p.quarter_end).toLocaleDateString() : 'N/A'}</td>
                                                    <td className="px-6 py-4 text-right font-mono">{p.promoter_pct?.toFixed(2)}%</td>
                                                    <td className="px-6 py-4 text-right font-mono">{p.fii_pct?.toFixed(2)}%</td>
                                                    <td className="px-6 py-4 text-right font-mono">{p.dii_pct?.toFixed(2)}%</td>
                                                    <td className="px-6 py-4 text-right font-mono">{p.public_pct?.toFixed(2)}%</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <div className="text-muted-foreground p-12 text-center border border-dashed border-border rounded-xl w-full">
                                    No shareholding / ownership data exists for this ticker yet.
                                </div>
                            )}
                        </div>
                    )}

                    {!loading && activeTab === 'ai' && (
                        <div className="flex-1 p-8 overflow-y-auto w-full">
                            <div className="flex items-center gap-3 mb-6 border-b border-border pb-4">
                                <Cpu className="w-8 h-8 text-purple-500" />
                                <div>
                                    <h2 className="text-2xl font-bold text-foreground">AI Conviction Engine</h2>
                                    <p className="text-sm text-muted-foreground">7 mathematical agents analyzing {ticker}'s raw underlying data.</p>
                                </div>
                            </div>

                            {data.aiAnalysis ? (() => {
                                const ai = data.aiAnalysis;
                                const SIGNAL_CFG = {
                                    STRONG_BUY:   { label: 'Strong Buy',   bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/40' },
                                    ACCUMULATE:   { label: 'Accumulate',   bg: 'bg-blue-500/15',    text: 'text-blue-400',    border: 'border-blue-500/40'    },
                                    AVOID:        { label: 'Avoid',        bg: 'bg-yellow-500/15',  text: 'text-yellow-400',  border: 'border-yellow-500/40'  },
                                    DISTRIBUTION: { label: 'Distribution', bg: 'bg-red-500/15',     text: 'text-red-400',     border: 'border-red-500/40'     },
                                };
                                const sig = SIGNAL_CFG[ai.signal] || { label: ai.signal || '—', bg: 'bg-muted/20', text: 'text-muted-foreground', border: 'border-border' };

                                const AgentCard = ({ title, icon, score, color, bgColor, borderColor, thesis }) => (
                                    <div className={`bg-card border rounded-xl p-5 shadow-sm ${borderColor || 'border-border'}`}>
                                        <div className="flex items-center justify-between mb-4">
                                            <h3 className={`text-base font-bold flex items-center gap-2 ${color}`}>{icon} {title}</h3>
                                            {score != null
                                                ? <div className={`text-2xl font-black ${color}`}>{score}<span className="text-xs text-muted-foreground font-normal">/100</span></div>
                                                : <div className="text-sm text-muted-foreground">N/A</div>
                                            }
                                        </div>
                                        {score != null && (
                                            <div className="w-full bg-muted rounded-full h-2 mb-4">
                                                <div className={`h-2 rounded-full transition-all ${bgColor}`} style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
                                            </div>
                                        )}
                                        {Array.isArray(thesis) && thesis.length > 0 && (
                                            <ul className="space-y-1.5 mt-2">
                                                {thesis.map((t, i) => (
                                                    <li key={i} className="text-xs flex items-start gap-1.5 text-muted-foreground">
                                                        <span className={`${color} mt-0.5 shrink-0`}>•</span> <span>{t}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                );

                                return (
                                    <div className="space-y-6">
                                        {/* Executive Signal Banner */}
                                        <div className={`rounded-xl border p-5 ${sig.bg} ${sig.border}`}>
                                            <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
                                                <div className="flex items-center gap-3">
                                                    <span className={`px-3 py-1 rounded-full text-sm font-bold border ${sig.bg} ${sig.text} ${sig.border}`}>
                                                        {sig.label}
                                                    </span>
                                                    {ai.regime && (
                                                        <span className="text-xs text-muted-foreground px-2 py-0.5 rounded-full border border-border/60 bg-background/50">
                                                            Regime: {ai.regime}
                                                        </span>
                                                    )}
                                                </div>
                                                {ai.final_score != null && (
                                                    <div className={`text-3xl font-black tabular-nums ${sig.text}`}>
                                                        {ai.final_score}<span className="text-sm text-muted-foreground font-normal">/100</span>
                                                    </div>
                                                )}
                                            </div>
                                            {Array.isArray(ai.signal_thesis) && ai.signal_thesis.length > 0 && (
                                                <ul className="space-y-1 mt-2">
                                                    {ai.signal_thesis.map((t, i) => (
                                                        <li key={i} className={`text-sm flex items-start gap-2 ${sig.text}`}>
                                                            <span className="mt-0.5 shrink-0">•</span> <span>{t}</span>
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>

                                        {/* Agent Cards Grid */}
                                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                                            <AgentCard
                                                title="Fundamental Analyst"
                                                icon={<FileText className="w-4 h-4" />}
                                                score={ai.fundamental_score}
                                                color="text-emerald-500"
                                                bgColor="bg-emerald-500"
                                                borderColor="border-emerald-500/20"
                                                thesis={ai.fundamental_thesis}
                                            />
                                            <AgentCard
                                                title="Technical Strategist"
                                                icon={<Activity className="w-4 h-4" />}
                                                score={ai.technical_score}
                                                color="text-blue-500"
                                                bgColor="bg-blue-500"
                                                borderColor="border-blue-500/20"
                                                thesis={ai.technical_thesis}
                                            />
                                            <AgentCard
                                                title="Macro Analyst"
                                                icon={<Globe className="w-4 h-4" />}
                                                score={ai.macro_score}
                                                color="text-yellow-500"
                                                bgColor="bg-yellow-500"
                                                borderColor="border-yellow-500/20"
                                                thesis={ai.macro_thesis}
                                            />
                                            <AgentCard
                                                title="Institutional Tracker"
                                                icon={<Briefcase className="w-4 h-4" />}
                                                score={ai.institutional_score}
                                                color="text-purple-500"
                                                bgColor="bg-purple-500"
                                                borderColor="border-purple-500/20"
                                                thesis={ai.institutional_thesis}
                                            />
                                            <AgentCard
                                                title="Sentiment Monitor"
                                                icon={<Share2 className="w-4 h-4" />}
                                                score={ai.sentiment_score}
                                                color="text-rose-500"
                                                bgColor="bg-rose-500"
                                                borderColor="border-rose-500/20"
                                                thesis={ai.sentiment_thesis}
                                            />
                                            {/* Memory Agent */}
                                            <div className="bg-card border border-cyan-500/20 rounded-xl p-5 shadow-sm">
                                                <div className="flex items-center justify-between mb-4">
                                                    <h3 className="text-base font-bold flex items-center gap-2 text-cyan-500">
                                                        <BarChart2 className="w-4 h-4" /> Historical Memory
                                                    </h3>
                                                    {ai.memory_confidence != null && (
                                                        <div className="text-2xl font-black text-cyan-500 tabular-nums">
                                                            {Math.round(ai.memory_confidence * 100)}
                                                            <span className="text-xs text-muted-foreground font-normal">%</span>
                                                        </div>
                                                    )}
                                                </div>
                                                {ai.memory_confidence != null && (
                                                    <div className="w-full bg-muted rounded-full h-2 mb-4">
                                                        <div className="h-2 rounded-full bg-cyan-500 transition-all" style={{ width: `${Math.round(ai.memory_confidence * 100)}%` }} />
                                                    </div>
                                                )}
                                                <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">Confidence</p>
                                                {Array.isArray(ai.memory_thesis) && ai.memory_thesis.length > 0 ? (
                                                    <ul className="space-y-1.5">
                                                        {ai.memory_thesis.map((t, i) => (
                                                            <li key={i} className="text-xs flex items-start gap-1.5 text-muted-foreground">
                                                                <span className="text-cyan-500 mt-0.5 shrink-0">•</span> <span>{t}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                ) : (
                                                    <p className="text-xs text-muted-foreground">No historical analog data available.</p>
                                                )}
                                            </div>

                                            {/* Vision Agent */}
                                            <div className="bg-card border border-indigo-500/20 rounded-xl p-5 shadow-sm">
                                                <div className="flex items-center justify-between mb-4">
                                                    <h3 className="text-base font-bold flex items-center gap-2 text-indigo-400">
                                                        <Activity className="w-4 h-4" /> Vision Agent
                                                    </h3>
                                                    {ai.vision_score != null && (
                                                        <div className="text-2xl font-black text-indigo-400 tabular-nums">
                                                            {ai.vision_score}
                                                            <span className="text-xs text-muted-foreground font-normal">/100</span>
                                                        </div>
                                                    )}
                                                </div>
                                                {ai.vision_score != null && (
                                                    <div className="w-full bg-muted rounded-full h-2 mb-4">
                                                        <div className="h-2 rounded-full bg-indigo-500 transition-all" style={{ width: `${Math.max(0, Math.min(100, ai.vision_score))}%` }} />
                                                    </div>
                                                )}
                                                <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">Chart Pattern Analysis</p>
                                                {Array.isArray(ai.vision_thesis) && ai.vision_thesis.length > 0 ? (
                                                    <ul className="space-y-1.5">
                                                        {ai.vision_thesis.map((t, i) => (
                                                            <li key={i} className="text-xs flex items-start gap-1.5 text-muted-foreground">
                                                                <span className="text-indigo-400 mt-0.5 shrink-0">•</span> <span>{t}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                ) : (
                                                    <p className="text-xs text-muted-foreground">No chart analysis available. Ensure charts have been generated.</p>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })() : (
                                <div className="text-muted-foreground p-12 text-center border border-dashed border-border rounded-xl w-full">
                                    <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4" />
                                    Generating real-time AI Analysis...
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
