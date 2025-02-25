import pandas as pd
from typing import Dict, Tuple
from modules.kenter_module import *
from modules.entsoe_module import *

class BatterySavingsCalculator:
    """Calculator for potential savings using battery storage system."""
    
    def __init__(self, battery_capacity: float = 100.0, enable_grid_arbitrage: bool = False, enable_solar_arbitrage: bool = True):
        self.battery_capacity = battery_capacity
        self.enable_grid_arbitrage = enable_grid_arbitrage
        self.enable_solar_arbitrage = enable_solar_arbitrage

    def arbitrage(self, energy_usage: pd.DataFrame, energy_prices: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate potential savings through arbitrage using battery storage.

        Args:
            energy_usage: DataFrame with columns [timestamp, type, value]
                where type is either 'return' or 'supply'
            energy_prices: DataFrame with columns [timestamp, price]

        Returns:
            DataFrame: Total potential savings with columns [timestamp, gross_savings, lost_revenue, net_savings, grid_arbitrage_savings]
        """
        # Initialize result DataFrame
        total_savings = pd.DataFrame({
            'timestamp': pd.Series(dtype='datetime64[ns]'),
            'gross_savings': pd.Series(dtype='float64'),
            'lost_revenue': pd.Series(dtype='float64'),
            'net_savings': pd.Series(dtype='float64'),
            'grid_arbitrage_savings': pd.Series(dtype='float64')
        })
        
        if not (self.enable_solar_arbitrage or self.enable_grid_arbitrage):
            return total_savings

        # Prepare data - do this once upfront
        energy_usage = energy_usage.copy()
        energy_prices = energy_prices.copy()
        
        # Convert timestamps to datetime and add date column efficiently
        energy_usage['timestamp'] = pd.to_datetime(energy_usage['timestamp'])
        energy_prices['timestamp'] = pd.to_datetime(energy_prices['timestamp'])
        energy_usage['date'] = energy_usage['timestamp'].dt.date
        energy_prices['date'] = energy_prices['timestamp'].dt.date

        # Split data once
        energy_return = energy_usage.query("type == 'return'")
        energy_supply = energy_usage.query("type == 'supply'")

        # Process each date more efficiently
        dates = energy_return['date'].unique()
        results = []

        for date in dates:
            # Filter data for current date using boolean indexing
            mask_return = energy_return['date'] == date
            mask_supply = energy_supply['date'] == date
            mask_prices = energy_prices['date'] == date
            
            day_data = {
                'return': energy_return[mask_return],
                'supply': energy_supply[mask_supply],
                'prices': energy_prices[mask_prices]
            }
            
            # Initialize savings components
            daily_surplus = 0
            gross_savings = 0
            lost_revenue = 0
            grid_arbitrage_savings = 0
            
            if self.enable_solar_arbitrage:
                # Calculate daily surplus energy from solar - vectorized
                daily_surplus = min(day_data['return']['value'].sum(), self.battery_capacity)
                
                if daily_surplus > 0:
                    # Merge prices with return data once
                    return_with_prices = pd.merge(
                        day_data['return'],
                        day_data['prices'][['timestamp', 'price']],
                        on='timestamp',
                        how='left'
                    )
                    
                    # Sort by price for efficient processing
                    return_with_prices = return_with_prices.sort_values('price')
                    
                    # Calculate lost revenue efficiently
                    cumsum = return_with_prices['value'].cumsum()
                    mask = cumsum <= daily_surplus
                    lost_revenue = (return_with_prices[mask]['value'] * return_with_prices[mask]['price']).sum()
                    
                    if not mask.all():
                        partial_amount = daily_surplus - cumsum[mask].iloc[-1] if len(cumsum[mask]) > 0 else daily_surplus
                        if partial_amount > 0:
                            lost_revenue += partial_amount * return_with_prices[~mask].iloc[0]['price']
                    
                    # Calculate gross savings efficiently
                    supply_with_prices = pd.merge(
                        day_data['supply'],
                        day_data['prices'][['timestamp', 'price']],
                        on='timestamp',
                        how='left'
                    ).sort_values('price', ascending=False)
                    
                    cumsum = supply_with_prices['value'].cumsum()
                    mask = cumsum <= daily_surplus
                    gross_savings = (supply_with_prices[mask]['value'] * supply_with_prices[mask]['price']).sum()
                    
                    if not mask.all():
                        partial_amount = daily_surplus - cumsum[mask].iloc[-1] if len(cumsum[mask]) > 0 else daily_surplus
                        if partial_amount > 0:
                            gross_savings += partial_amount * supply_with_prices[~mask].iloc[0]['price']
            
            # Calculate grid arbitrage savings if enabled
            if self.enable_grid_arbitrage:
                remaining_battery_capacity = self.battery_capacity - daily_surplus
                
                if remaining_battery_capacity > 0:
                    # Get day's price data and sort by time
                    day_prices = day_data['prices'].sort_values('timestamp')
                    
                    # Vectorized calculation of price opportunities
                    timestamps = day_prices['timestamp'].values
                    prices = day_prices['price'].values
                    
                    opportunities = []
                    for i in range(len(timestamps)):
                        for j in range(i + 1, len(timestamps)):
                            price_diff = prices[j] - prices[i]
                            if price_diff > 0:
                                opportunities.append({
                                    'buy_time': timestamps[i],
                                    'sell_time': timestamps[j],
                                    'buy_price': prices[i],
                                    'sell_price': prices[j],
                                    'profit_per_kwh': price_diff
                                })
                    
                    if opportunities:
                        # Convert to DataFrame for efficient processing
                        opportunities_df = pd.DataFrame(opportunities)
                        opportunities_df = opportunities_df.sort_values('profit_per_kwh', ascending=False)
                        
                        remaining_capacity = remaining_battery_capacity
                        for _, opp in opportunities_df.iterrows():
                            if remaining_capacity <= 0:
                                break
                                
                            sell_time_supply = energy_supply[
                                (energy_supply['timestamp'] == opp['sell_time']) &
                                (energy_supply['date'] == date)
                            ]['value'].iloc[0] if not energy_supply[
                                (energy_supply['timestamp'] == opp['sell_time']) &
                                (energy_supply['date'] == date)
                            ].empty else 0
                            
                            tradeable_amount = min(
                                remaining_capacity,
                                sell_time_supply
                            )
                            
                            if tradeable_amount > 0:
                                cost_to_buy = tradeable_amount * opp['buy_price']
                                saved_cost = tradeable_amount * opp['sell_price']
                                grid_arbitrage_savings += saved_cost - cost_to_buy
                                remaining_capacity -= tradeable_amount
            
            # Only append if there are actual transactions
            if gross_savings > 0 or lost_revenue > 0 or grid_arbitrage_savings > 0:
                results.append({
                    'timestamp': date,
                    'gross_savings': gross_savings,
                    'lost_revenue': lost_revenue,
                    'net_savings': gross_savings - lost_revenue,
                    'grid_arbitrage_savings': grid_arbitrage_savings
                })
        
        if results:
            total_savings = pd.DataFrame(results)
        
        return total_savings




if __name__ == "__main__":
    usage_df = get_kenter_data(
                        "2024-02-25",
                        "2024-02-27",
                        interval='15min'
                    )
    price = get_energy_prices(
                        "2024-02-25",
                        "2024-02-27",
    )
    bm = BatterySavingsCalculator()
    bm.arbitrage(usage_df, price)


