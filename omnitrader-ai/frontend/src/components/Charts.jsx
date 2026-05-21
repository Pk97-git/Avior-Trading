import React, { useState, useEffect, useCallback } from 'react';
import { Search, BarChart2, Grid3x3, Clock, Loader2, RefreshCw } from 'lucide-react';
import CandlestickPanel from './charts/CandlestickPanel';
import HeatmapView from './charts/HeatmapView';
import MultiTimeframeView from './charts/MultiTimeframeView';
import { chartsApi, patternsApi } from '../api';

const PERIODS = ['1mo','3mo','6mo','1y','2y','5y'];
const INTERVALS = [
    { label: '1D', value: '1d' },
    { label: '1W', value: '1wk' },
    { label: '1Mo', value: '1mo' },
];
const VIEWS = [
    { id: 'chart', label: 'Chart', icon: BarChart2 },
    { id: 'multi', label: 'Multi-TF', icon: Clock },
    { id: 'heatmap', label: 'Heatmap', icon: Grid3x3 },
];

const QUICK_TICKERS_IN = ['RELIANCE.NS','TCS.NS','HDFCBANK.NS','INFY.NS','ICICIBANK.NS','TATAMOTORS.NS','SBIN.NS','WIPRO.NS'];
const QUICK_TICKERS_US = ['AAPL','MSFT','NVDA','GOOGL','AMZN','TSLA','META','JPM'];

export default function Charts() {
    const [view, setView] = useState('chart');
    const [ticker, setTicker] = useState('RELIANCE.NS');
    const [searchInput, setSearchInput] = useState('');
    const [period, setPeriod] = useState('1y');
    const [interval, setInterval] = useState('1d');
    const [chartData, setChartData] = useState(null);
    const [annotations, setAnnotations] = useState(null);
    const [multiData, setMultiData] = useState(null);
    const [patternAnnotations, setPatternAnnotations] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const loadChart = useCallback(async (t, p, i) => {
        if (!t) return;
        setLoading(true);
        setError(null);
        try {
            const [ohlcvRes, annoRes] = await Promise.all([
                chartsApi.getOHLCV(t, p, i),
                chartsApi.getAnnotations(t).catch(() => ({ data: { markers: [], current_levels: null } })),
            ]);
            setChartData(ohlcvRes.data);
            setAnnotations(annoRes.data);
        } catch (e) {
            setError(`Failed to load chart data for ${t}`);
        } finally {
            setLoading(false);
        }
    }, []);

    const loadPatterns = useCallback(async (t) => {
        if (!t) return;
        try {
            const res = await patternsApi.getChartAnnotations(t);
            setPatternAnnotations(res.data);
        } catch {
            setPatternAnnotations(null);
        }
    }, []);

    const loadMulti = useCallback(async (t) => {
        if (!t) return;
        try {
            const res = await chartsApi.getMultiTimeframe(t);
            setMultiData(res.data);
        } catch (e) {
            console.error('Multi-TF load failed:', e);
        }
    }, []);

    useEffect(() => {
        loadChart(ticker, period, interval);
        loadPatterns(ticker);
        if (view === 'multi') loadMulti(ticker);
    }, [ticker, period, interval]);

    useEffect(() => {
        if (view === 'multi' && !multiData) loadMulti(ticker);
    }, [view]);

    const handleSearch = (e) => {
        e.preventDefault();
        const t = searchInput.trim().toUpperCase();
        if (t) { setTicker(t); setSearchInput(''); }
    };

    const handleQuickTicker = (t) => {
        setTicker(t);
    };

    return (
        <div className="flex flex-col h-full bg-zinc-950 text-zinc-100">
            {/* Top bar */}
            <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-wrap bg-zinc-900">
                {/* Ticker search */}
                <form onSubmit={handleSearch} className="flex items-center gap-1">
                    <div className="relative">
                        <Search className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-500" size={14} />
                        <input
                            value={searchInput}
                            onChange={e => setSearchInput(e.target.value)}
                            placeholder="Search ticker..."
                            className="pl-7 pr-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-sm text-zinc-100 placeholder-zinc-500 w-40 focus:outline-none focus:border-zinc-500"
                        />
                    </div>
                    <button type="submit" className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 rounded text-sm transition-colors">Go</button>
                </form>

                {/* Current ticker */}
                <span className="text-zinc-400 font-mono font-semibold">{ticker}</span>

                <div className="w-px h-5 bg-zinc-700" />

                {/* Period selector */}
                <div className="flex gap-1">
                    {PERIODS.map(p => (
                        <button key={p} onClick={() => setPeriod(p)}
                            className={`px-2 py-1 text-xs rounded transition-colors ${period === p ? 'bg-zinc-600 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
                        >{p}</button>
                    ))}
                </div>

                <div className="w-px h-5 bg-zinc-700" />

                {/* Interval selector */}
                <div className="flex gap-1">
                    {INTERVALS.map(iv => (
                        <button key={iv.value} onClick={() => setInterval(iv.value)}
                            className={`px-2 py-1 text-xs rounded transition-colors ${interval === iv.value ? 'bg-zinc-600 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
                        >{iv.label}</button>
                    ))}
                </div>

                <div className="w-px h-5 bg-zinc-700" />

                {/* View toggle */}
                <div className="flex rounded overflow-hidden border border-zinc-700">
                    {VIEWS.map(v => (
                        <button key={v.id} onClick={() => setView(v.id)}
                            className={`flex items-center gap-1 px-3 py-1 text-xs transition-colors ${view === v.id ? 'bg-zinc-600 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
                        >
                            <v.icon size={12} />
                            {v.label}
                        </button>
                    ))}
                </div>

                <button onClick={() => loadChart(ticker, period, interval)}
                    className="ml-auto p-1.5 text-zinc-500 hover:text-zinc-300 transition-colors" title="Refresh">
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            {/* Quick tickers */}
            <div className="flex items-center gap-1 px-4 py-1.5 border-b border-zinc-800 bg-zinc-900/50 overflow-x-auto">
                <span className="text-xs text-zinc-600 mr-1 shrink-0">Quick:</span>
                {[...QUICK_TICKERS_IN, ...QUICK_TICKERS_US].map(t => (
                    <button key={t} onClick={() => handleQuickTicker(t)}
                        className={`px-2 py-0.5 text-xs rounded shrink-0 transition-colors ${ticker === t ? 'bg-zinc-600 text-white' : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'}`}
                    >{t.replace('.NS','').replace('.BO','')}</button>
                ))}
            </div>

            {/* Main content */}
            <div className="flex-1 min-h-0 overflow-hidden relative">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/50 z-10">
                        <Loader2 className="animate-spin text-zinc-400" size={32} />
                    </div>
                )}
                {error && (
                    <div className="flex items-center justify-center h-full text-zinc-500 text-sm">{error}</div>
                )}
                {!error && view === 'chart' && chartData && (
                    <div className="h-full p-2">
                        <CandlestickPanel ticker={ticker} data={chartData} annotations={annotations} patternAnnotations={patternAnnotations} />
                    </div>
                )}
                {!error && view === 'multi' && (
                    <MultiTimeframeView ticker={ticker} multiData={multiData} />
                )}
                {!error && view === 'heatmap' && (
                    <HeatmapView chartsApi={chartsApi} />
                )}
            </div>
        </div>
    );
}
