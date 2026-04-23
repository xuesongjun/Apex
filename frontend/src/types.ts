export interface AccountOption {
  account_id: string;
  strategy_key: string;
  stock_codes: string[];
  updated_at?: string | null;
  created_at?: string | null;
}

export interface DashboardOverview {
  account_id: string;
  strategy_key: string;
  stock_codes: string[];
  initial_capital: number;
  cash: number;
  market_value: number;
  total_equity: number;
  nav: number;
  total_profit: number;
  total_profit_pct: number;
  total_commission: number;
  total_tax: number;
  position_count: number;
  pending_count: number;
  latest_trade_date?: string | null;
}

export interface PositionItem {
  code: string;
  volume: number;
  available: number;
  cost_price: number;
  current_price: number;
  market_value: number;
  profit: number;
  profit_pct: number;
  buy_date?: string | null;
}

export interface PendingOrderItem {
  order_id: string;
  code: string;
  direction: string;
  req_volume: number;
  execute_date?: string | null;
  signal_date: string;
  status: string;
  reason: string;
}

export interface NavPoint {
  trade_date: string;
  total_equity: number;
  cash?: number | null;
  market_value?: number | null;
  nav?: number | null;
  daily_pnl?: number | null;
}

export interface DashboardPayload {
  accounts: AccountOption[];
  selected_account_id?: string | null;
  overview?: DashboardOverview | null;
  positions: PositionItem[];
  pending_orders: PendingOrderItem[];
  nav: NavPoint[];
}
