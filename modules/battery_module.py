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
        # Prepare data
        energy_usage = energy_usage.copy()
        energy_prices = energy_prices.copy()
        
        # Add date column for grouping
        energy_usage['date'] = pd.to_datetime(energy_usage['timestamp']).dt.date
        energy_prices['date'] = pd.to_datetime(energy_prices['timestamp']).dt.date

        # Split into return and supply
        energy_return = energy_usage.query("type == 'return'")
        energy_supply = energy_usage.query("type == 'supply'")

        # Initialize total_savings with proper columns and dtypes
        total_savings = pd.DataFrame({
            'timestamp': pd.Series(dtype='datetime64[ns]'),
            'gross_savings': pd.Series(dtype='float64'),
            'lost_revenue': pd.Series(dtype='float64'),
            'net_savings': pd.Series(dtype='float64'),
            'grid_arbitrage_savings': pd.Series(dtype='float64')
        })
        
        # Process each date
        for date in energy_return['date'].unique():
            # Filter data for current date
            day_data = {
                'return': energy_return[energy_return['date'] == date],
                'supply': energy_supply[energy_supply['date'] == date],
                'prices': energy_prices[energy_prices['date'] == date]
            }
            
            # Initialize savings components
            daily_surplus = 0
            gross_savings = 0
            lost_revenue = 0
            grid_arbitrage_savings = 0
            
            if self.enable_solar_arbitrage:
                # Calculate daily surplus energy from solar
                daily_surplus = day_data['return']['value'].sum() 
                # Limit surplus to battery capacity
                daily_surplus = min(daily_surplus, self.battery_capacity)
                
                # Calculate lost revenue from not selling surplus
                return_with_prices = pd.merge(
                    day_data['return'],
                    day_data['prices'],
                    on='timestamp',
                    how='left'
                )
                
                # Sort by price to prioritize storing energy during lowest price periods
                return_with_prices = return_with_prices.sort_values('price')
                
                # Calculate lost revenue from solar
                remaining_capacity = daily_surplus
                for _, row in return_with_prices.iterrows():
                    if remaining_capacity <= 0:
                        break
                        
                    storable_energy = min(remaining_capacity, row['value'])
                    lost_revenue += storable_energy * row['price']
                    remaining_capacity -= storable_energy
                
                # Sort supply by price to identify most expensive periods
                expensive_supply = pd.merge(
                    day_data['prices'].sort_values('price', ascending=False),
                    day_data['supply'],
                    on='timestamp',
                    how='left'
                )
                
                # Calculate potential gross savings from solar
                remaining_surplus = daily_surplus
                for _, row in expensive_supply.iterrows():
                    if remaining_surplus <= 0:
                        break
                        
                    usable_energy = min(remaining_surplus, row['value'])
                    gross_savings += usable_energy * row['price']
                    remaining_surplus -= usable_energy
            
            # Calculate grid arbitrage savings if enabled
            if self.enable_grid_arbitrage:
                # Calculate remaining battery capacity after solar storage
                remaining_battery_capacity = self.battery_capacity - daily_surplus
                
                if remaining_battery_capacity > 0:
                    # Get day's price data and sort by time
                    day_prices = day_data['prices'].sort_values('timestamp')
                    
                    # Calculate price differentials for each possible buy-sell pair
                    price_opportunities = []
                    for buy_idx, buy_row in day_prices.iterrows():
                        for sell_idx, sell_row in day_prices.iterrows():
                            if sell_idx <= buy_idx:  # Can't sell before we buy
                                continue
                            
                            price_diff = sell_row['price'] - buy_row['price']
                            if price_diff > 0:  # Only consider profitable opportunities
                                price_opportunities.append({
                                    'buy_time': buy_row['timestamp'],
                                    'sell_time': sell_row['timestamp'],
                                    'buy_price': buy_row['price'],
                                    'sell_price': sell_row['price'],
                                    'profit_per_kwh': price_diff
                                })
                    
                    # Sort opportunities by profit potential
                    price_opportunities.sort(key=lambda x: x['profit_per_kwh'], reverse=True)
                    
                    # Calculate potential energy to buy/sell at each opportunity
                    for opportunity in price_opportunities:
                        if remaining_battery_capacity <= 0:
                            break
                            
                        # Find how much energy we need at sell_time
                        sell_time_supply = energy_supply[
                            energy_supply['timestamp'] == opportunity['sell_time']
                        ]['value'].iloc[0] if not energy_supply[
                            energy_supply['timestamp'] == opportunity['sell_time']
                        ].empty else 0
                        
                        # Calculate how much we can profitably trade
                        tradeable_amount = min(
                            remaining_battery_capacity,  # Battery limit
                            sell_time_supply  # Actual need at sell time
                        )
                        
                        if tradeable_amount > 0:
                            # Calculate profit from this trade
                            cost_to_buy = tradeable_amount * opportunity['buy_price']
                            saved_cost = tradeable_amount * opportunity['sell_price']
                            grid_arbitrage_savings += saved_cost - cost_to_buy
                            
                            # Update remaining capacity
                            remaining_battery_capacity -= tradeable_amount
            
            # Only append if there are actual transactions
            if gross_savings > 0 or lost_revenue > 0 or grid_arbitrage_savings > 0:
                new_row = pd.DataFrame({
                    'timestamp': [date],
                    'gross_savings': [gross_savings],
                    'lost_revenue': [lost_revenue],
                    'net_savings': [gross_savings - lost_revenue],
                    'grid_arbitrage_savings': [grid_arbitrage_savings]
                })
                total_savings = pd.concat([total_savings, new_row], ignore_index=True)
        
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


