"""
brokers/paper.py
================
Simulated paper broker — fills all orders immediately at the provided
price hint.  No real money is ever moved.  Used as the fallback when no
real-broker credentials are configured, and as a testing harness.
"""
from app.brokers.base import BrokerInterface, OrderResult, Position, AccountBalance


class PaperBroker(BrokerInterface):
    """
    Simulated broker — always works, no real money.
    Used when no real broker env vars are set, and for testing.
    Fills MARKET orders immediately at the provided price hint.
    """

    name = "PAPER"

    def __init__(self) -> None:
        self._orders: dict[str, OrderResult] = {}
        self._next_id: int = 1
        self._balance = AccountBalance(
            cash=100_000.0,
            portfolio_value=100_000.0,
            buying_power=100_000.0,
        )

    async def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        limit_price: float | None = None,
    ) -> OrderResult:
        oid = f"PAPER-{self._next_id:06d}"
        self._next_id += 1

        # Paper: fill immediately at limit_price (or 0.0 if not provided)
        fill_price = limit_price or 0.0
        result = OrderResult(
            broker_order_id=oid,
            status="FILLED",
            filled_qty=qty,
            filled_price=fill_price,
            message=f"Paper fill: {side} {qty} {ticker} @ {fill_price}",
        )
        self._orders[oid] = result
        return result

    async def get_order_status(self, broker_order_id: str) -> OrderResult:
        return self._orders.get(
            broker_order_id,
            OrderResult(broker_order_id=broker_order_id, status="NOT_FOUND"),
        )

    async def cancel_order(self, broker_order_id: str) -> bool:
        if broker_order_id in self._orders:
            self._orders[broker_order_id].status = "CANCELLED"
            return True
        return False

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account_balance(self) -> AccountBalance:
        return self._balance
