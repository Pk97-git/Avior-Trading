import React, { useEffect, useState } from 'react';

// Color helpers
function returnColor(pct) {
    // Strong green → green → neutral → red → strong red
    if (pct >  5) return 'bg-green-600 text-white';
    if (pct >  2) return 'bg-green-700 text-green-100';
    if (pct >  0.5) return 'bg-green-900 text-green-300';
    if (pct > -0.5) return 'bg-zinc-800 text-zinc-300';
    if (pct > -2) return 'bg-red-900 text-red-300';
    if (pct > -5) return 'bg-red-700 text-red-100';
    return 'bg-red-600 text-white';
}

function aiScoreColor(score) {
    if (score >= 70) return 'bg-green-700 text-green-100';
    if (score >= 55) return 'bg-emerald-900 text-emerald-300';
    if (score >= 45) return 'bg-zinc-800 text-zinc-300';
    if (score >= 35) return 'bg-orange-900 text-orange-300';
    return 'bg-red-900 text-red-300';
}

// Sector Heatmap — colored grid
function SectorHeatmap({ sectors }) {
    if (!sectors?.length) return (
        <div className="flex items-center justify-center h-64 text-zinc-500 text-sm">No sector data</div>
    );
    return (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 p-2">
            {sectors.map(s => (
                <div
                    key={s.name}
                    className={`rounded-lg p-3 border border-zinc-700/50 cursor-default transition-all hover:scale-105 ${returnColor(s.return_pct)}`}
                >
                    <div className="font-semibold text-sm truncate">{s.name}</div>
                    <div className="text-xl font-bold font-mono mt-1">
                        {s.return_pct >= 0 ? '+' : ''}{s.return_pct?.toFixed(2)}%
                    </div>
                    <div className="text-xs mt-1 opacity-75">{s.stock_count} stocks · AI {s.avg_ai_score}</div>
                    {s.best_performer && (
                        <div className="text-xs mt-1 opacity-60">
                            ▲ {s.best_performer.ticker} {s.best_performer.return_pct?.toFixed(1)}%
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}

// Market Heatmap — treemap style blocks sized by market cap
function MarketHeatmap({ stocks, metric }) {
    if (!stocks?.length) return (
        <div className="flex items-center justify-center h-64 text-zinc-500 text-sm">No market data</div>
    );

    // Normalize market caps for sizing (min 60px, max proportional to sqrt of market cap)
    const maxCap = Math.max(...stocks.map(s => s.market_cap || 1));

    const getSize = (cap) => {
        const ratio = Math.sqrt((cap || 1) / maxCap);
        return Math.max(60, Math.round(ratio * 200));
    };

    const getColorClass = (s) => {
        return metric === 'ai_score' ? aiScoreColor(s.ai_score) : returnColor(s.value);
    };

    return (
        <div className="flex flex-wrap gap-1 p-2 content-start">
            {stocks.slice(0, 60).map(s => {
                const size = getSize(s.market_cap);
                return (
                    <div
                        key={s.ticker}
                        className={`rounded flex flex-col items-center justify-center text-center p-1 cursor-default hover:opacity-90 transition-opacity ${getColorClass(s)}`}
                        style={{ width: `${size}px`, height: `${Math.max(50, size * 0.7)}px` }}
                        title={`${s.name}\n${metric === 'ai_score' ? 'AI Score: ' + s.ai_score : 'Return: ' + s.value?.toFixed(2) + '%'}`}
                    >
                        <div className="font-bold text-xs leading-tight truncate w-full text-center">
                            {s.ticker.replace('.NS', '').replace('.BO', '')}
                        </div>
                        <div className="text-xs font-mono">
                            {metric === 'ai_score'
                                ? s.ai_score
                                : `${s.value >= 0 ? '+' : ''}${s.value?.toFixed(1)}%`
                            }
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

export default function HeatmapView({ chartsApi }) {
    const [heatmapType, setHeatmapType] = useState('sectors');  // 'sectors' | 'market'
    const [sectorPeriod, setSectorPeriod] = useState('1mo');
    const [marketMetric, setMarketMetric] = useState('return_1d');
    const [country, setCountry] = useState('IN');
    const [sectorData, setSectorData] = useState(null);
    const [marketData, setMarketData] = useState(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            setLoading(true);
            try {
                if (heatmapType === 'sectors') {
                    const res = await chartsApi.getSectorHeatmap(sectorPeriod, country);
                    if (!cancelled) setSectorData(res.data);
                } else {
                    const res = await chartsApi.getMarketHeatmap(marketMetric, country);
                    if (!cancelled) setMarketData(res.data);
                }
            } catch (e) {
                console.error('Heatmap load failed:', e);
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        load();
        return () => { cancelled = true; };
    }, [heatmapType, sectorPeriod, marketMetric, country]);

    return (
        <div className="flex flex-col h-full">
            {/* Controls */}
            <div className="flex items-center gap-3 p-3 border-b border-zinc-800 flex-wrap">
                <div className="flex rounded overflow-hidden border border-zinc-700">
                    {['sectors', 'market'].map(t => (
                        <button
                            key={t}
                            onClick={() => setHeatmapType(t)}
                            className={`px-3 py-1 text-xs capitalize transition-colors ${heatmapType === t ? 'bg-zinc-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
                        >{t === 'sectors' ? 'Sector Map' : 'Market Map'}</button>
                    ))}
                </div>

                <div className="flex rounded overflow-hidden border border-zinc-700">
                    {['IN', 'US'].map(c => (
                        <button key={c} onClick={() => setCountry(c)}
                            className={`px-3 py-1 text-xs ${country === c ? 'bg-zinc-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
                        >{c}</button>
                    ))}
                </div>

                {heatmapType === 'sectors' && (
                    <div className="flex rounded overflow-hidden border border-zinc-700">
                        {['1d','1wk','1mo','3mo'].map(p => (
                            <button key={p} onClick={() => setSectorPeriod(p)}
                                className={`px-3 py-1 text-xs ${sectorPeriod === p ? 'bg-zinc-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
                            >{p}</button>
                        ))}
                    </div>
                )}

                {heatmapType === 'market' && (
                    <div className="flex rounded overflow-hidden border border-zinc-700">
                        {[
                            ['return_1d', '1D'],
                            ['return_1w', '1W'],
                            ['return_1mo', '1M'],
                            ['ai_score', 'AI Score'],
                        ].map(([v, l]) => (
                            <button key={v} onClick={() => setMarketMetric(v)}
                                className={`px-3 py-1 text-xs ${marketMetric === v ? 'bg-zinc-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}
                            >{l}</button>
                        ))}
                    </div>
                )}

                {/* Legend */}
                <div className="ml-auto flex items-center gap-1 text-xs text-zinc-500">
                    <span className="bg-green-700 text-white px-1 rounded">+</span>
                    <span>Gain</span>
                    <span className="bg-zinc-800 text-zinc-300 px-1 rounded ml-1">~</span>
                    <span>Flat</span>
                    <span className="bg-red-700 text-white px-1 rounded ml-1">-</span>
                    <span>Loss</span>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto">
                {loading ? (
                    <div className="flex items-center justify-center h-full text-zinc-500">Loading...</div>
                ) : heatmapType === 'sectors' ? (
                    <SectorHeatmap sectors={sectorData?.sectors} />
                ) : (
                    <MarketHeatmap stocks={marketData?.stocks} metric={marketMetric} />
                )}
            </div>
        </div>
    );
}
