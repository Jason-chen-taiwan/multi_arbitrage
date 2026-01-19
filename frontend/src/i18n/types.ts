export type Language = 'zh' | 'en'

export interface Translations {
  // Common
  common: {
    save: string
    reload: string
    delete: string
    cancel: string
    confirm: string
    loading: string
    success: string
    error: string
    status: string
    running: string
    stopped: string
    syncAgo: string
  }

  // Navigation
  nav: {
    marketMaker: string
    arbitrage: string
    settings: string
    comparison: string
  }

  // Market Maker Page
  mm: {
    title: string
    startMM: string
    stopMM: string
    starting: string
    stopping: string
    dryRunMode: string
    liveTrading: string

    // Config sections
    strategyConfig: string
    quoteParams: string
    positionParams: string
    volatilityControl: string
    executionControl: string

    // Quote params
    orderDistance: string
    cancelDistance: string
    rebalanceDistance: string
    queueLimit: string

    // Position params
    orderSize: string
    maxPosition: string

    // Volatility params
    observeWindow: string
    pauseThreshold: string
    resumeThreshold: string

    // Units
    bps: string
    sec: string
    levels: string

    // Cards
    totalPnl: string
    uptime: string
    position: string
    fills: string
    effectivePoints: string
    totalFills: string
    hedged: string
    notHedged: string

    // Order book
    orderBook: string
    price: string
    size: string
    spread: string
    noOrderBookData: string

    // Positions panel
    positions: string
    netPosition: string
    lastSync: string

    // Fill history
    recentFills: string
    time: string
    side: string
    qty: string
    value: string
    noFills: string

    // Status bar
    netExposure: string
    equity: string
    sync: string

    // Execution stats
    executionStats: string
    runningTime: string
    effectiveScore: string
    fillCount: string
    livePnl: string
    tierDistribution: string
    tier100: string
    tier50: string
    tier10: string
    tierOver: string
    bidStats: string
    askStats: string
    cancelQueueRebalance: string
    volatility: string
    normal: string
    paused: string
    pauseCount: string

    // Maker Hours
    makerHoursEstimate: string
    mm1Target: string
    mm2Target: string
    perHour: string
    perMonth: string

    // Uptime Program
    uptimeProgram: string
    boosted: string
    standard: string
    inactive: string
    currentMultiplier: string

    // Depth Analysis
    depthAnalysis: string
    bidDepth: string
    askDepth: string
    imbalance: string
    queuePosition: string
    buyOrderPosition: string
    sellOrderPosition: string
    level: string

    // Current Orders
    currentOrders: string
    bidOrder: string
    askOrder: string
    waitingToPlace: string
    midPrice: string
    maxDistance: string

    // Messages
    configSaved: string
    configReloaded: string
    configSaveFailed: string
    configReloadFailed: string
  }

  // Settings Page
  settings: {
    title: string
    addExchange: string
    exchangeName: string
    exchangeType: string
    selectExchange: string
    authMode: string
    walletMode: string
    tokenMode: string
    apiKey: string
    apiSecret: string
    privateKey: string
    walletAddress: string
    tradingAccountId: string
    saveConfig: string
    saveAndStart: string
    configuredExchanges: string
    noExchanges: string
    systemControls: string
    reconnectAll: string
    reinitSystem: string
    deletedConfig: string
    savedConfig: string
    failedSave: string
    failedDelete: string
    reconnected: string
    reconnectFailed: string
    reinitialized: string
    reinitFailed: string
  }

  // Arbitrage Page
  arbitrage: {
    title: string
    autoExecute: string
    liveTrading: string
    opportunities: string
    priceTable: string
    noData: string
  }

  // Comparison Page
  comparison: {
    title: string
    simControl: string
    duration: string
    minutes: string
    startSim: string
    stopSim: string
    selected: string
    paramSets: string
    noParamSets: string
    liveComparison: string
    paramSetName: string
    uptimePercent: string
    fillCount: string
    started: string
    startFailed: string
    simStopped: string
    stopFailed: string
    selectAtLeastOne: string
    elapsed: string
    remaining: string
  }
}
