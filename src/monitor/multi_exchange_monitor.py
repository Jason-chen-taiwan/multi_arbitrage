"""
多交易所實時監控系統
Multi-Exchange Real-time Monitoring System

實時監控多個交易所的價格、訂單簿和套利機會
"""
import asyncio
from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
import json

from src.adapters.factory import create_adapter
from src.adapters.base_adapter import BasePerpAdapter, Orderbook


@dataclass
class MarketData:
    """市場數據"""
    exchange: str
    symbol: str
    best_bid: Decimal
    best_ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    spread: Decimal
    spread_pct: Decimal
    timestamp: datetime
    orderbook: Optional[Orderbook] = None


@dataclass
class ArbitrageOpportunity:
    """套利機會"""
    buy_exchange: str
    sell_exchange: str
    symbol: str
    buy_price: Decimal
    sell_price: Decimal
    profit: Decimal
    profit_pct: Decimal
    buy_size: Decimal
    sell_size: Decimal
    max_quantity: Decimal
    timestamp: datetime

    def __str__(self):
        return (
            f"🔥 {self.symbol} Arbitrage:\n"
            f"  Buy:  {self.buy_exchange.upper():10s} @ ${self.buy_price:10.2f} (size: {self.buy_size})\n"
            f"  Sell: {self.sell_exchange.upper():10s} @ ${self.sell_price:10.2f} (size: {self.sell_size})\n"
            f"  💰 Profit: ${self.profit:8.2f} ({self.profit_pct:6.4f}%)\n"
            f"  📊 Max Qty: {self.max_quantity}"
        )


class MultiExchangeMonitor:
    """多交易所監控器"""

    def __init__(
        self,
        adapters: Dict[str, BasePerpAdapter],
        symbols: List[str],
        update_interval: float = 2.0,
        min_profit_pct: float = 0.1  # 最小套利利潤 0.1%
    ):
        """
        初始化監控器

        Args:
            adapters: 交易所適配器字典 {exchange_name: adapter}
            symbols: 要監控的交易對列表
            update_interval: 更新間隔（秒）
            min_profit_pct: 最小套利利潤百分比
        """
        self.adapters = adapters
        self.symbols = symbols
        self.update_interval = update_interval
        self.min_profit_pct = min_profit_pct

        # 市場數據緩存
        self.market_data: Dict[str, Dict[str, MarketData]] = defaultdict(dict)
        # {exchange: {symbol: MarketData}}

        # 套利機會緩存
        self.arbitrage_opportunities: List[ArbitrageOpportunity] = []

        # 統計數據
        self.stats = {
            'total_updates': 0,
            'total_opportunities': 0,
            'failed_updates': defaultdict(int)
        }

        self._running = False
        self._tasks = []

    async def start(self):
        """啟動監控"""
        if self._running:
            print("⚠️  Monitor is already running")
            return

        self._running = True
        print(f"\n{'='*80}")
        print(f"🚀 Starting Multi-Exchange Monitor")
        print(f"{'='*80}")
        print(f"📊 Monitoring {len(self.symbols)} symbols on {len(self.adapters)} exchanges")
        print(f"⏱️  Update interval: {self.update_interval}s")
        print(f"💰 Min profit threshold: {self.min_profit_pct}%")
        print(f"{'='*80}\n")

        # 為每個交易所創建監控任務
        for exchange_name, adapter in self.adapters.items():
            task = asyncio.create_task(
                self._monitor_exchange(exchange_name, adapter)
            )
            self._tasks.append(task)

        # 創建套利檢測任務
        arbitrage_task = asyncio.create_task(self._detect_arbitrage())
        self._tasks.append(arbitrage_task)

        # 創建統計顯示任務
        stats_task = asyncio.create_task(self._display_stats())
        self._tasks.append(stats_task)

    async def stop(self):
        """停止監控"""
        print("\n🛑 Stopping monitor...")
        self._running = False

        # 取消所有任務
        for task in self._tasks:
            task.cancel()

        # 等待任務完成
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        print("✅ Monitor stopped")

    async def _monitor_exchange(self, exchange_name: str, adapter: BasePerpAdapter):
        """監控單個交易所"""
        while self._running:
            try:
                # 並行獲取所有交易對的訂單簿
                tasks = [
                    adapter.get_orderbook(symbol, limit=10)
                    for symbol in self.symbols
                ]
                orderbooks = await asyncio.gather(*tasks, return_exceptions=True)

                # 處理每個訂單簿
                for symbol, orderbook in zip(self.symbols, orderbooks):
                    if isinstance(orderbook, Exception):
                        self.stats['failed_updates'][exchange_name] += 1
                        continue

                    # 計算市場數據
                    if orderbook.bids and orderbook.asks:
                        best_bid = orderbook.bids[0][0]
                        best_ask = orderbook.asks[0][0]
                        bid_size = orderbook.bids[0][1]
                        ask_size = orderbook.asks[0][1]
                        spread = best_ask - best_bid
                        spread_pct = (spread / best_bid * 100)

                        market_data = MarketData(
                            exchange=exchange_name,
                            symbol=symbol,
                            best_bid=best_bid,
                            best_ask=best_ask,
                            bid_size=bid_size,
                            ask_size=ask_size,
                            spread=spread,
                            spread_pct=spread_pct,
                            timestamp=datetime.now(),
                            orderbook=orderbook
                        )

                        self.market_data[exchange_name][symbol] = market_data
                        self.stats['total_updates'] += 1

            except Exception as e:
                print(f"❌ {exchange_name} monitoring error: {e}")
                self.stats['failed_updates'][exchange_name] += 1

            await asyncio.sleep(self.update_interval)

    async def _detect_arbitrage(self):
        """檢測套利機會"""
        while self._running:
            try:
                opportunities = []

                # 對每個交易對
                for symbol in self.symbols:
                    # 獲取所有交易所的市場數據
                    markets = []
                    for exchange_name in self.adapters.keys():
                        if symbol in self.market_data[exchange_name]:
                            markets.append(self.market_data[exchange_name][symbol])

                    # 需要至少 2 個交易所有數據
                    if len(markets) < 2:
                        continue

                    # 檢查所有交易所對
                    for i in range(len(markets)):
                        for j in range(i + 1, len(markets)):
                            market_a = markets[i]
                            market_b = markets[j]

                            # 檢查 A 買 B 賣
                            profit_ab = market_b.best_bid - market_a.best_ask
                            profit_pct_ab = (profit_ab / market_a.best_ask * 100)

                            if profit_pct_ab > self.min_profit_pct:
                                max_qty = min(market_a.ask_size, market_b.bid_size)
                                opportunity = ArbitrageOpportunity(
                                    buy_exchange=market_a.exchange,
                                    sell_exchange=market_b.exchange,
                                    symbol=symbol,
                                    buy_price=market_a.best_ask,
                                    sell_price=market_b.best_bid,
                                    profit=profit_ab,
                                    profit_pct=profit_pct_ab,
                                    buy_size=market_a.ask_size,
                                    sell_size=market_b.bid_size,
                                    max_quantity=max_qty,
                                    timestamp=datetime.now()
                                )
                                opportunities.append(opportunity)
                                self.stats['total_opportunities'] += 1

                            # 檢查 B 買 A 賣
                            profit_ba = market_a.best_bid - market_b.best_ask
                            profit_pct_ba = (profit_ba / market_b.best_ask * 100)

                            if profit_pct_ba > self.min_profit_pct:
                                max_qty = min(market_b.ask_size, market_a.bid_size)
                                opportunity = ArbitrageOpportunity(
                                    buy_exchange=market_b.exchange,
                                    sell_exchange=market_a.exchange,
                                    symbol=symbol,
                                    buy_price=market_b.best_ask,
                                    sell_price=market_a.best_bid,
                                    profit=profit_ba,
                                    profit_pct=profit_pct_ba,
                                    buy_size=market_b.ask_size,
                                    sell_size=market_a.bid_size,
                                    max_quantity=max_qty,
                                    timestamp=datetime.now()
                                )
                                opportunities.append(opportunity)
                                self.stats['total_opportunities'] += 1

                # 更新套利機會列表
                self.arbitrage_opportunities = opportunities

                # 顯示套利機會
                if opportunities:
                    print(f"\n{'='*80}")
                    print(f"💰 ARBITRAGE OPPORTUNITIES DETECTED: {len(opportunities)}")
                    print(f"{'='*80}")
                    for opp in opportunities:
                        print(f"\n{opp}")
                    print(f"{'='*80}\n")

            except Exception as e:
                print(f"❌ Arbitrage detection error: {e}")

            await asyncio.sleep(self.update_interval / 2)  # 檢測頻率更高

    async def _display_stats(self):
        """顯示統計信息"""
        while self._running:
            await asyncio.sleep(10)  # 每 10 秒顯示一次

            print(f"\n{'='*80}")
            print(f"📊 MONITOR STATISTICS")
            print(f"{'='*80}")
            print(f"⏱️  Runtime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"📈 Total Updates: {self.stats['total_updates']}")
            print(f"💰 Total Opportunities Found: {self.stats['total_opportunities']}")

            # 顯示每個交易所的狀態
            print(f"\n📊 Exchange Status:")
            for exchange_name in self.adapters.keys():
                symbol_count = len(self.market_data[exchange_name])
                failed_count = self.stats['failed_updates'][exchange_name]
                print(f"  {exchange_name.upper():15s} - Symbols: {symbol_count}/{len(self.symbols)}, Failures: {failed_count}")

            # 顯示當前價格
            print(f"\n💵 Current Prices:")
            for symbol in self.symbols:
                print(f"\n  {symbol}:")
                for exchange_name in self.adapters.keys():
                    if symbol in self.market_data[exchange_name]:
                        data = self.market_data[exchange_name][symbol]
                        print(f"    {exchange_name.upper():15s} - Bid: ${data.best_bid:10.2f} | Ask: ${data.best_ask:10.2f} | Spread: {data.spread_pct:6.4f}%")

            print(f"{'='*80}\n")

    def get_market_data(self, exchange: str, symbol: str) -> Optional[MarketData]:
        """獲取特定交易所和交易對的市場數據"""
        return self.market_data.get(exchange, {}).get(symbol)

    def get_all_market_data(self, symbol: str) -> List[MarketData]:
        """獲取特定交易對在所有交易所的市場數據"""
        markets = []
        for exchange_name in self.adapters.keys():
            data = self.get_market_data(exchange_name, symbol)
            if data:
                markets.append(data)
        return markets

    def get_best_prices(self, symbol: str) -> Dict[str, Decimal]:
        """獲取特定交易對的最佳買賣價"""
        markets = self.get_all_market_data(symbol)
        if not markets:
            return {}

        best_bid_market = max(markets, key=lambda m: m.best_bid)
        best_ask_market = min(markets, key=lambda m: m.best_ask)

        return {
            'best_bid': best_bid_market.best_bid,
            'best_bid_exchange': best_bid_market.exchange,
            'best_ask': best_ask_market.best_ask,
            'best_ask_exchange': best_ask_market.exchange,
            'spread': best_ask_market.best_ask - best_bid_market.best_bid
        }

    def export_data(self, filename: str = 'market_data.json'):
        """導出市場數據到 JSON"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'stats': {
                'total_updates': self.stats['total_updates'],
                'total_opportunities': self.stats['total_opportunities'],
                'failed_updates': dict(self.stats['failed_updates'])
            },
            'market_data': {},
            'arbitrage_opportunities': []
        }

        # 導出市場數據
        for exchange, symbols_data in self.market_data.items():
            data['market_data'][exchange] = {}
            for symbol, market in symbols_data.items():
                data['market_data'][exchange][symbol] = {
                    'best_bid': str(market.best_bid),
                    'best_ask': str(market.best_ask),
                    'spread': str(market.spread),
                    'spread_pct': str(market.spread_pct),
                    'timestamp': market.timestamp.isoformat()
                }

        # 導出套利機會
        for opp in self.arbitrage_opportunities:
            data['arbitrage_opportunities'].append({
                'buy_exchange': opp.buy_exchange,
                'sell_exchange': opp.sell_exchange,
                'symbol': opp.symbol,
                'buy_price': str(opp.buy_price),
                'sell_price': str(opp.sell_price),
                'profit': str(opp.profit),
                'profit_pct': str(opp.profit_pct),
                'max_quantity': str(opp.max_quantity),
                'timestamp': opp.timestamp.isoformat()
            })

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"✅ Data exported to {filename}")
