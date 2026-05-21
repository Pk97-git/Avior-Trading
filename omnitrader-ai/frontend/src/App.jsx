import React, { useState } from 'react';
import {
    LayoutDashboard, Database, Activity, Settings, Globe, Zap,
    Award, Star, BarChart2, TrendingUp, FlaskConical, Briefcase,
    ShoppingCart, Calendar, Layers, ShieldAlert, BarChart, Newspaper, Users,
    Menu, X, BookOpen, Filter, GitCompare, Calculator, TrendingDown,
    MessageSquare, Eye, PieChart,
} from 'lucide-react';
import IngestionDashboard from './components/IngestionDashboard';
import StockUniverse from './components/StockUniverse';
import Dashboard from './components/Dashboard';
import MarketAnalysis from './components/MarketAnalysis';
import IntelligenceHub from './components/IntelligenceHub';
import Compounders from './components/Compounders';
import LiveJobsView from './components/LiveJobsView';
import Watchlist from './components/Watchlist';
import Portfolio from './components/Portfolio';
import Orders from './components/Orders';
import SignalPerformance from './components/SignalPerformance';
import SettingsPage from './components/Settings';
import SwingSetups from './components/SwingSetups';
import Backtest from './components/Backtest';
import EarningsCalendar from './components/EarningsCalendar';
import OptionsFlow from './components/OptionsFlow';
import SectorRotation from './components/SectorRotation';
import RiskDashboard from './components/RiskDashboard';
import DailyBriefing from './components/DailyBriefing';
import InsiderActivity from './components/InsiderActivity';
import AnalystRatings from './components/AnalystRatings';
import EconomicCalendar from './components/EconomicCalendar';
import Charts from './components/Charts';
import PatternScanner from './components/PatternScanner';
import Screener from './components/Screener';
import PairsTrading from './components/PairsTrading';
import PositionSizerPanel from './components/PositionSizer';
import StressTest from './components/StressTest';
import FactorExposure from './components/FactorExposure';
import EarningsNLP from './components/EarningsNLP';
import DarkPool from './components/DarkPool';
import QuantAnalysis from './components/QuantAnalysis';
import AlphaSignals from './components/AlphaSignals';
import PortfolioOptimizer from './components/PortfolioOptimizer';

const TABS = [
    // ── Core ──────────────────────────────────────────────────
    { id: 'briefing',     label: 'Daily Briefing',      icon: Newspaper },
    { id: 'dashboard',    label: 'Dashboard',           icon: LayoutDashboard },
    { id: 'hub',          label: 'Intelligence Hub',    icon: Zap },
    { id: 'swing',        label: 'Swing Setups',        icon: TrendingUp },
    // ── Positions ─────────────────────────────────────────────
    { id: 'watchlist',    label: 'Watchlist',           icon: Star },
    { id: 'portfolio',    label: 'Portfolio',           icon: Briefcase },
    { id: 'orders',       label: 'Orders',              icon: ShoppingCart },
    // ── Alpha ─────────────────────────────────────────────────
    { id: 'earnings',     label: 'Earnings Calendar',   icon: Calendar },
    { id: 'options',      label: 'Options Flow',        icon: Layers },
    { id: 'insiders',     label: 'Insider Activity',    icon: Users },
    { id: 'analysts',     label: 'Analyst Ratings',     icon: Star },
    { id: 'econCalendar', label: 'Economic Calendar',   icon: Calendar },
    { id: 'sectors',      label: 'Sector Rotation',     icon: BarChart },
    // ── Risk & Analytics ──────────────────────────────────────
    { id: 'risk',            label: 'Risk Dashboard',   icon: ShieldAlert },
    { id: 'factors',         label: 'Factor Exposure',  icon: Layers },
    { id: 'shorts',          label: 'Short Candidates', icon: TrendingDown },
    { id: 'position-sizer',  label: 'Position Sizer',   icon: Calculator },
    { id: 'stress-test',     label: 'Stress Test',      icon: ShieldAlert },
    { id: 'performance',     label: 'Signal Performance', icon: BarChart2 },
    { id: 'backtest',        label: 'Backtest',          icon: FlaskConical },
    { id: 'quant',           label: 'Quant Analysis',    icon: FlaskConical },
    { id: 'optimizer',       label: 'Portfolio Optimizer', icon: PieChart },
    // ── Research ──────────────────────────────────────────────
    { id: 'screener',     label: 'Screener',            icon: Filter },
    { id: 'market',       label: 'Market Analysis',     icon: Activity },
    { id: 'compounders',  label: 'Compounders',         icon: Award },
    { id: 'charts',       label: 'Charts',              icon: BarChart2 },
    { id: 'patterns',     label: 'Pattern Scanner',     icon: TrendingUp },
    { id: 'pairs',        label: 'Pairs Trading',       icon: GitCompare },
    { id: 'earnings-nlp', label: 'Earnings Tone',       icon: MessageSquare },
    { id: 'dark-pool',    label: 'Dark Pool',           icon: Eye },
    { id: 'alpha',        label: 'Alpha Signals',       icon: Zap },
    // ── Data ──────────────────────────────────────────────────
    { id: 'data',         label: 'Data Ingestion',      icon: Database },
    { id: 'jobs',         label: 'Active Jobs',         icon: Activity },
    { id: 'universe',     label: 'Stock Universe',      icon: Globe },
];

const TAB_LABELS = Object.fromEntries(TABS.map(t => [t.id, t.label]));

const MOBILE_TABS = [
    { id: 'briefing',  label: 'Brief',     icon: BookOpen },
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'swing',     label: 'Swing',     icon: TrendingUp },
    { id: 'portfolio', label: 'Portfolio', icon: Briefcase },
    { id: 'patterns',  label: 'Patterns',  icon: BarChart2 },
    { id: 'settings',  label: 'Settings',  icon: Settings },
];

// Grouped sidebar sections for visual clarity
const NAV_GROUPS = [
    { label: 'Core',           ids: ['briefing', 'dashboard', 'hub', 'swing'] },
    { label: 'Positions',      ids: ['watchlist', 'portfolio', 'orders'] },
    { label: 'Alpha',          ids: ['earnings', 'options', 'insiders', 'analysts', 'econCalendar', 'sectors'] },
    { label: 'Risk & Analytics', ids: ['risk', 'factors', 'shorts', 'position-sizer', 'stress-test', 'performance', 'backtest', 'quant', 'optimizer'] },
    { label: 'Research',       ids: ['screener', 'market', 'compounders', 'charts', 'patterns', 'pairs', 'earnings-nlp', 'dark-pool', 'alpha'] },
    { label: 'Data',           ids: ['data', 'jobs', 'universe'] },
];

function NavItem({ icon: Icon, label, active, onClick }) {
    return (
        <button
            onClick={onClick}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                }`}
        >
            <Icon size={16} />
            <span>{label}</span>
        </button>
    );
}

export default function App() {
    const [activeTab, setActiveTab] = useState('briefing');
    const [hubTicker, setHubTicker] = useState(null);
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

    const handleNavigate = (tab, extra = null) => {
        if (tab === 'hub' && extra) setHubTicker(extra);
        setActiveTab(tab);
        setMobileMenuOpen(false);
    };

    const tabMap = Object.fromEntries(TABS.map(t => [t.id, t]));

    return (
        <div className="flex h-screen bg-background text-foreground font-sans">

            {/* ── Sidebar — desktop only ── */}
            <aside className="w-52 border-r border-border bg-card/50 backdrop-blur-sm py-4 hidden md:flex flex-col shrink-0 overflow-y-auto">
                <div className="px-4 mb-4 flex items-center gap-2">
                    <Activity className="h-5 w-5 text-primary shrink-0" />
                    <h1 className="text-base font-bold tracking-tight">OmniTrader AI</h1>
                </div>

                <nav className="flex-1 px-2 space-y-4">
                    {NAV_GROUPS.map(group => (
                        <div key={group.label}>
                            <p className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                                {group.label}
                            </p>
                            <div className="space-y-0.5">
                                {group.ids.map(id => {
                                    const tab = tabMap[id];
                                    if (!tab) return null;
                                    return (
                                        <NavItem
                                            key={id}
                                            icon={tab.icon}
                                            label={tab.label}
                                            active={activeTab === id}
                                            onClick={() => handleNavigate(id)}
                                        />
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </nav>

                <div className="px-2 pt-3 border-t border-border mt-4">
                    <NavItem
                        icon={Settings}
                        label="Settings"
                        active={activeTab === 'settings'}
                        onClick={() => handleNavigate('settings')}
                    />
                </div>
            </aside>

            {/* ── Mobile drawer overlay ── */}
            {mobileMenuOpen && (
                <div
                    className="fixed inset-0 bg-black/60 z-40 md:hidden"
                    onClick={() => setMobileMenuOpen(false)}
                />
            )}

            {/* ── Mobile drawer ── */}
            <div className={`fixed top-0 left-0 bottom-0 w-64 bg-card border-r border-border z-50 flex flex-col py-4
                            transition-transform duration-200 md:hidden
                            ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'}`}>
                <div className="px-4 mb-4 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Activity className="h-5 w-5 text-primary shrink-0" />
                        <h1 className="text-base font-bold tracking-tight">OmniTrader AI</h1>
                    </div>
                    <button onClick={() => setMobileMenuOpen(false)} className="p-1 text-muted-foreground hover:text-foreground">
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <nav className="flex-1 px-2 space-y-4 overflow-y-auto">
                    {NAV_GROUPS.map(group => (
                        <div key={group.label}>
                            <p className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                                {group.label}
                            </p>
                            <div className="space-y-0.5">
                                {group.ids.map(id => {
                                    const tab = tabMap[id];
                                    if (!tab) return null;
                                    return (
                                        <NavItem
                                            key={id}
                                            icon={tab.icon}
                                            label={tab.label}
                                            active={activeTab === id}
                                            onClick={() => handleNavigate(id)}
                                        />
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </nav>

                <div className="px-2 pt-3 border-t border-border mt-4">
                    <NavItem
                        icon={Settings}
                        label="Settings"
                        active={activeTab === 'settings'}
                        onClick={() => handleNavigate('settings')}
                    />
                </div>
            </div>

            {/* ── Main ── */}
            <main className="flex-1 overflow-auto min-w-0 flex flex-col">

                {/* Desktop header */}
                <header className="h-14 border-b border-border items-center px-6 bg-card/50 backdrop-blur-sm sticky top-0 z-10 hidden md:flex">
                    <h2 className="text-base font-semibold">
                        {TAB_LABELS[activeTab] || 'Settings'}
                    </h2>
                </header>

                {/* Mobile header */}
                <div className="flex md:hidden items-center justify-between px-4 py-3
                                bg-slate-900 border-b border-slate-700/60 sticky top-0 z-40">
                    <span className="font-bold text-sky-400 text-sm">OmniTrader AI</span>
                    <span className="text-slate-400 text-xs">{TAB_LABELS[activeTab] || 'Settings'}</span>
                    <button onClick={() => setMobileMenuOpen(true)}>
                        <Menu className="h-5 w-5 text-slate-400" />
                    </button>
                </div>

                <div className="p-4 md:p-6 pb-20 md:pb-6 flex-1 overflow-auto">
                    {activeTab === 'briefing'    && <DailyBriefing onNavigate={handleNavigate} />}
                    {activeTab === 'dashboard'   && <Dashboard onNavigate={handleNavigate} />}
                    {activeTab === 'hub'         && <IntelligenceHub key={hubTicker} initialTicker={hubTicker} />}
                    {activeTab === 'swing'       && <SwingSetups onNavigate={handleNavigate} />}
                    {activeTab === 'watchlist'   && <Watchlist onNavigate={handleNavigate} />}
                    {activeTab === 'portfolio'   && <Portfolio onNavigate={handleNavigate} />}
                    {activeTab === 'orders'      && <Orders onNavigate={handleNavigate} />}
                    {activeTab === 'earnings'    && <EarningsCalendar onNavigate={handleNavigate} />}
                    {activeTab === 'options'     && <OptionsFlow onNavigate={handleNavigate} />}
                    {activeTab === 'insiders'    && <InsiderActivity onNavigate={handleNavigate} />}
                    {activeTab === 'analysts'    && <AnalystRatings onNavigate={handleNavigate} />}
                    {activeTab === 'econCalendar' && <EconomicCalendar />}
                    {activeTab === 'sectors'     && <SectorRotation />}
                    {activeTab === 'risk'           && <RiskDashboard onNavigate={handleNavigate} />}
                    {activeTab === 'factors'        && <FactorExposure view="factors" />}
                    {activeTab === 'shorts'         && <FactorExposure view="shorts" />}
                    {activeTab === 'position-sizer' && <PositionSizerPanel />}
                    {activeTab === 'stress-test'    && <StressTest onNavigate={handleNavigate} />}
                    {activeTab === 'performance' && <SignalPerformance />}
                    {activeTab === 'backtest'    && <Backtest />}
                    {activeTab === 'quant'       && <QuantAnalysis />}
                    {activeTab === 'optimizer'   && <PortfolioOptimizer />}
                    {activeTab === 'screener'    && <Screener onNavigate={handleNavigate} />}
                    {activeTab === 'market'      && <MarketAnalysis />}
                    {activeTab === 'compounders' && <Compounders />}
                    {activeTab === 'charts'      && <Charts />}
                    {activeTab === 'patterns'    && <PatternScanner onNavigate={handleNavigate} />}
                    {activeTab === 'pairs'        && <PairsTrading />}
                    {activeTab === 'earnings-nlp' && <EarningsNLP />}
                    {activeTab === 'dark-pool'    && <DarkPool />}
                    {activeTab === 'alpha'        && <AlphaSignals />}
                    {activeTab === 'data'        && <IngestionDashboard onNavigate={handleNavigate} />}
                    {activeTab === 'jobs'        && <LiveJobsView />}
                    {activeTab === 'universe'    && <StockUniverse onNavigate={handleNavigate} />}
                    {activeTab === 'settings'    && <SettingsPage />}
                </div>
            </main>

            {/* ── Bottom nav — mobile only ── */}
            <div className="fixed bottom-0 left-0 right-0 bg-slate-900 border-t border-slate-700/60
                            flex md:hidden z-50">
                {MOBILE_TABS.map(tab => (
                    <button key={tab.id}
                        onClick={() => handleNavigate(tab.id)}
                        className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px]
                            ${activeTab === tab.id
                                ? 'text-sky-400'
                                : 'text-slate-500'}`}
                    >
                        <tab.icon className="h-5 w-5" />
                        {tab.label}
                    </button>
                ))}
            </div>
        </div>
    );
}
