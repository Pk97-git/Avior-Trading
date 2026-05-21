import axios from 'axios';

const api = axios.create({
    baseURL: '/api/v1',
    headers: { 'Content-Type': 'application/json' },
});

export const ingestionApi = {
    getStatus: () => api.get('/ingestion/status'),
    getPrices: (ticker, country, limit = 50) => api.get('/ingestion/prices', { params: { ticker: ticker?.toUpperCase(), country, limit } }),
    getFundamentals: (ticker, country) => api.get('/ingestion/fundamentals', { params: { ticker: ticker?.toUpperCase(), country } }),
    getMacro: (indicator) => api.get('/ingestion/macro', { params: { indicator } }),
    getInstitutional: (market, type) => api.get('/ingestion/institutional', { params: { market, entity_type: type } }),
    getSentiment: (ticker, country) => api.get('/ingestion/sentiment', { params: { ticker: ticker?.toUpperCase(), country } }),
    getPromoter: (ticker, country) => api.get('/ingestion/promoter', { params: { ticker: ticker?.toUpperCase(), country } }),
    getTickers: (page = 1, limit = 50, search = null, filters = {}) =>
        api.get('/ingestion/tickers', { params: { page, limit, search, ...filters } }),
    getSectorBreakdown: () => api.get('/ingestion/sector-breakdown'),
    triggerFetch: (source) => api.post(`/ingestion/trigger/${source}`),
    triggerNow: (flow) => api.post(`/ingestion/trigger-now/${flow}`),
    getHealth: () => api.get('/ingestion/health'),
    getDataProgress: () => api.get('/ingestion/data-progress'),
    getLiveJobs: () => api.get('/ingestion/active-jobs'),
};

export const agentsApi = {
    // Per-ticker analysis
    getAnalysis: (ticker) => api.get(`/agents/analysis/${ticker}`),
    triggerAnalysis: (ticker) => api.post(`/agents/analyze/${ticker}`),

    // Dashboard & signals
    getDashboard: () => api.get('/agents/dashboard'),
    getSignals: (params) => api.get('/agents/signals', { params }),
    getMarketAnalysis: () => api.get('/agents/market-analysis'),
    getCompounders: (params) => api.get('/agents/compounders', { params }),

    // Alert management
    markAlertsRead: (ids = []) => api.post('/agents/alerts/mark-read', ids),

    // Performance & system
    getSignalPerformance: (days = 90) => api.get('/agents/performance', { params: { days } }),
    getSystemStatus: () => api.get('/agents/system-status'),
};

export const backtestApi = {
    run: (params) => api.post('/backtest/run', params),
    quickStats: (country = null) => api.get('/backtest/quick-stats', { params: country ? { country } : {} }),
};

export const watchlistApi = {
    getWatchlist: () => api.get('/watchlist'),
    addTicker: (ticker, priority = 'MEDIUM', notes = null) =>
        api.post(`/watchlist/${ticker.toUpperCase()}`, { priority, notes }),
    removeTicker: (ticker) => api.delete(`/watchlist/${ticker.toUpperCase()}`),
    updateEntry: (ticker, updates) => api.patch(`/watchlist/${ticker.toUpperCase()}`, updates),
};

export const portfolioApi = {
    getPositions: () => api.get('/portfolio'),
    getSummary:   () => api.get('/portfolio/summary'),
    getHistory:   (page = 1, limit = 20) => api.get('/portfolio/history', { params: { page, limit } }),
    openPosition: (ticker, data) => api.post(`/portfolio/${ticker.toUpperCase()}`, data),
    updatePosition: (id, data) => api.patch(`/portfolio/${id}`, data),
    closePosition:  (id, data) => api.post(`/portfolio/${id}/close`, data),
};

export const circuitBreakerApi = {
    getStatus: () => api.get('/circuit-breaker/status'),
};

export const ordersApi = {
    submitFromAnalysis: (ticker, body = {}) => api.post(`/orders/submit/${ticker.toUpperCase()}`, body),
    submitManual: (body) => api.post('/orders/manual', body),
    listOrders: (params = {}) => api.get('/orders', { params }),
    getOrder: (id) => api.get(`/orders/${id}`),
    cancelOrder: (id) => api.post(`/orders/${id}/cancel`),
    getBrokerBalance: (country = 'US') => api.get('/orders/broker/balance', { params: { country } }),
    getBrokerPositions: (country = 'US') => api.get('/orders/broker/positions', { params: { country } }),
    syncBroker: () => api.post('/orders/broker/sync'),
};

export const earningsApi = {
    getCalendar:  (params = {}) => api.get('/earnings/calendar', { params }),
    getTicker:    (ticker) => api.get(`/earnings/calendar/${ticker.toUpperCase()}`),
    getBestSetups: (params = {}) => api.get('/earnings/calendar/setups/best', { params }),
};

export const optionsApi = {
    getUnusual:   (params = {}) => api.get('/options/unusual', { params }),
    getPutCall:   (ticker) => api.get(`/options/put-call/${ticker.toUpperCase()}`),
    getChain:     (ticker, expiry = null) => api.get(`/options/chain/${ticker.toUpperCase()}`, { params: expiry ? { expiry } : {} }),
};

export const sectorsApi = {
    getRotation: () => api.get('/sectors/rotation'),
    getHistory:  (etf, days = 90) => api.get('/sectors/rotation/history', { params: { sector_etf: etf, days } }),
};

export const riskApi = {
    getPortfolioRisk:    () => api.get('/risk/portfolio-risk'),
    getCorrelation:      () => api.get('/risk/correlation-matrix'),
    getRsRankings:       (params = {}) => api.get('/risk/rs-rankings', { params }),
    getTickerRs:         (ticker) => api.get(`/risk/rs-rankings/${ticker.toUpperCase()}`),
};

export const briefingApi = {
    getDaily:  (force = false) => api.get('/briefing/daily', { params: force ? { force: true } : {} }),
    refresh:   () => api.post('/briefing/refresh'),
};

export const insidersApi = {
    getRecent:    (params = {}) => api.get('/insiders/recent', { params }),
    getTicker:    (ticker) => api.get(`/insiders/${ticker.toUpperCase()}`),
    getUniverse:  () => api.get('/insiders/stats/universe'),
};

export const analystsApi = {
    getRecent:    (params = {}) => api.get('/analysts/recent', { params }),
    getTicker:    (ticker) => api.get(`/analysts/${ticker.toUpperCase()}`),
    getConsensus: (ticker) => api.get(`/analysts/consensus/${ticker.toUpperCase()}`),
};

export const economicCalendarApi = {
    getEvents:   (days = 30) => api.get('/economic-calendar/events', { params: { days_ahead: days } }),
    getBlackout: () => api.get('/economic-calendar/events/blackout'),
};

export const trailingStopsApi = {
    run:         () => api.post('/trailing-stops/run'),
    runSingle:   (positionId) => api.post(`/trailing-stops/${positionId}`),
    getConfig:   () => api.get('/trailing-stops/config'),
    setConfig:   (body) => api.put('/trailing-stops/config', body),
};

export const chartsApi = {
    getOHLCV: (ticker, period = '1y', interval = '1d') =>
        api.get(`/charts/ohlcv/${ticker.toUpperCase()}`, { params: { period, interval } }),
    getAnnotations: (ticker, days = 365) =>
        api.get(`/charts/annotations/${ticker.toUpperCase()}`, { params: { days } }),
    getSectorHeatmap: (period = '1mo', country = 'IN') =>
        api.get('/charts/heatmap/sectors', { params: { period, country } }),
    getMarketHeatmap: (metric = 'return_1d', country = 'IN', limit = 50) =>
        api.get('/charts/heatmap/market', { params: { metric, country, limit } }),
    getMultiTimeframe: (ticker) =>
        api.get(`/charts/multi/${ticker.toUpperCase()}`),
};

export const notificationsApi = {
    getPreferences:   () => api.get('/notifications/preferences'),
    savePreferences:  (body) => api.put('/notifications/preferences', body),
    sendTest:         () => api.post('/notifications/test'),
    preview:          () => api.get('/notifications/preview'),
};

export const patternsApi = {
    getTicker: (ticker, params = {}) =>
        api.get(`/patterns/${ticker.toUpperCase()}`, { params }),
    scanToday: (params = {}) =>
        api.get('/patterns/scan/today', { params }),
    backtest: (body) =>
        api.post('/patterns/backtest', body),
    listAll: () =>
        api.get('/patterns/list'),
    getChartAnnotations: (ticker, params = {}) =>
        api.get(`/patterns/${ticker.toUpperCase()}/chart-annotations`, { params }),
};

export const screenerApi = {
    run:          (body) => api.post('/screener/run', body),
    getFields:    () => api.get('/screener/fields'),
    getTemplates: () => api.get('/screener/templates'),
    getSaved:     () => api.get('/screener/saved'),
    save:         (body) => api.post('/screener/save', body),
};

export default api;
