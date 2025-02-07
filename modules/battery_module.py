import pandas as pd
from typing import Dict, Tuple
from modules.kenter_module import *
from modules.entsoe_module import *

class BatterySavingsCalculator:
    """Calculator for potential savings using battery storage system."""
    
    def __init__(self, battery_capacity: float = 100.0):
        self.battery_capacity = battery_capacity

    def arbitrage(self, energy_usage: pd.DataFrame, energy_prices: pd.DataFrame) -> float:
        """
        Calculate potential savings through arbitrage using battery storage.

        Args:
            energy_usage: DataFrame with columns [timestamp, type, value]
                where type is either 'return' or 'supply'
            energy_prices: DataFrame with columns [timestamp, price]

        Returns:
            float: Total potential savings in euros
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
            'savings': pd.Series(dtype='float64')
        })
        
        # Process each date
        for date in energy_return['date'].unique():
            # Filter data for current date
            day_data = {
                'return': energy_return[energy_return['date'] == date],
                'supply': energy_supply[energy_supply['date'] == date],
                'prices': energy_prices[energy_prices['date'] == date]
            }
            
            # Calculate daily surplus energy
            daily_surplus = day_data['return']['value'].sum() 
            # Limit surplus to battery capacity
            daily_surplus = min(daily_surplus, self.battery_capacity)
            
            # Sort supply by price to identify most expensive periods
            expensive_supply = pd.merge(
                day_data['prices'].sort_values('price', ascending=False),
                day_data['supply'],
                on='timestamp',
                how='left'
            )
            
            # Calculate potential savings for the day
            remaining_surplus = daily_surplus
            daily_savings = 0
            for _, row in expensive_supply.iterrows():
                if remaining_surplus <= 0:
                    break
                    
                usable_energy = min(remaining_surplus, row['value'])
                daily_savings  += usable_energy * row['price']
                remaining_surplus -= usable_energy
                # Append daily savings to the DataFrame
                if daily_savings > 0:  # Only append if there are actual savings
                    new_row = pd.DataFrame({
                        'timestamp': [date],
                        'savings': [daily_savings]
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


