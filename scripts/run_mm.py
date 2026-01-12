"""
Market Maker Runner Script

Main entry point for running the market making bot.
"""

import os
import sys
import asyncio
import signal
from decimal import Decimal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv

from src.exchange import StandXExchange
from src.strategy import SimpleMarketMaker, AdaptiveMarketMaker, UptimeMarketMaker
from src.risk import RiskManager, RiskLimits


class MarketMakerBot:
    """Main market maker bot orchestrator."""
    
    def __init__(self, config_path: str):
        """
        Initialize market maker bot.
        
        Args:
            config_path: Path to configuration file
        """
        # Load environment variables
        load_dotenv()
        
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Initialize components
        self.exchange = None
        self.strategy = None
        self.risk_manager = None
        self.is_running = False
    
    async def initialize(self):
        """Initialize all components."""
        print("="*60)
        print("🚀 StandX Market Maker Bot")
        print("="*60)
        
        # Initialize exchange
        exchange_config = {
            'name': 'standx',
            'chain': self.config['exchange']['chain'],
            'wallet_private_key': os.getenv('WALLET_PRIVATE_KEY'),
            'base_url': self.config['exchange']['base_url'],
            'perps_url': self.config['exchange']['perps_url']
        }
        
        self.exchange = StandXExchange(exchange_config)
        
        # Connect to exchange
        print("\n📡 Connecting to exchange...")
        connected = await self.exchange.connect()
        if not connected:
            raise Exception("Failed to connect to exchange")
        
        # Initialize risk manager
        risk_config = self.config['risk']
        risk_limits = RiskLimits(
            max_position_value=Decimal(str(risk_config['max_position_value'])),
            max_leverage=risk_config['max_leverage'],
            max_daily_loss=Decimal(str(risk_config['max_daily_loss'])),
            max_trade_loss=Decimal(str(risk_config.get('max_trade_loss', 100))),
            max_drawdown=Decimal(str(risk_config['max_drawdown'])),
            max_open_orders=self.config['trading'].get('max_open_orders', 10)
        )
        
        self.risk_manager = RiskManager(risk_limits)
        
        # Initialize strategy
        strategy_name = self.config['strategy']['name']
        strategy_config = {**self.config['trading'], **self.config['strategy']}
        
        print(f"\n📊 Initializing strategy: {strategy_name}")
        
        if strategy_name == 'simple_mm':
            self.strategy = SimpleMarketMaker(self.exchange, strategy_config)
        elif strategy_name == 'adaptive_mm':
            self.strategy = AdaptiveMarketMaker(self.exchange, strategy_config)
        elif strategy_name == 'uptime_mm':
            self.strategy = UptimeMarketMaker(self.exchange, strategy_config)
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        
        print("\n✅ All components initialized")
        print("="*60)
    
    async def run(self):
        """Run the market maker bot."""
        self.is_running = True
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # Start risk monitoring task
            risk_task = asyncio.create_task(self._monitor_risk())
            
            # Start strategy
            strategy_task = asyncio.create_task(self.strategy.start())
            
            # Wait for tasks
            await asyncio.gather(risk_task, strategy_task)
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.shutdown()
    
    async def _monitor_risk(self):
        """Monitor risk metrics periodically."""
        while self.is_running:
            try:
                # Get current state
                position = await self.exchange.get_position(self.strategy.symbol)
                balance = await self.exchange.get_balance()
                open_orders = await self.exchange.get_open_orders(self.strategy.symbol)
                
                # Update risk metrics
                self.risk_manager.update_metrics(
                    position=position,
                    balance=balance,
                    open_orders_count=len(open_orders)
                )
                
                # Check risk limits
                within_limits, violation_reason = self.risk_manager.check_risk_limits()
                
                if not within_limits:
                    print(f"\n⚠️  RISK VIOLATION: {violation_reason}")
                    
                    # Stop strategy if halted
                    if self.risk_manager.is_halted:
                        await self.strategy.stop()
                        self.is_running = False
                
                # Display risk summary periodically
                if self.config['monitoring'].get('enable_dashboard', True):
                    print(self.risk_manager.get_risk_summary())
                
                await asyncio.sleep(self.config['monitoring'].get('metrics_interval', 10))
                
            except Exception as e:
                print(f"❌ Risk monitoring error: {e}")
                await asyncio.sleep(5)
    
    async def shutdown(self):
        """Graceful shutdown."""
        print("\n🛑 Shutting down...")
        
        self.is_running = False
        
        if self.strategy:
            await self.strategy.stop()
        
        if self.exchange:
            await self.exchange.disconnect()
        
        print("✅ Shutdown complete")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\n⚠️  Received signal {signum}")
        self.is_running = False


async def main():
    """Main entry point."""
    # Get config path from command line or use default
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = 'config/config.yaml'
    
    if not os.path.exists(config_path):
        print(f"❌ Configuration file not found: {config_path}")
        sys.exit(1)
    
    # Create and run bot
    bot = MarketMakerBot(config_path)
    await bot.initialize()
    await bot.run()


if __name__ == '__main__':
    # Run the bot
    asyncio.run(main())
