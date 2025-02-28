import pandas as pd
import numpy as np
from typing import Dict, Tuple, List
from modules.kenter_module import *
from modules.entsoe_module import *

class BatterySavingsCalculator:
    """Calculator for potential savings using battery storage system."""
    
    def __init__(self, battery_capacity: float = 100.0, enable_grid_arbitrage: bool = False, 
                 enable_solar_arbitrage: bool = True, charge_efficiency: float = 0.95, 
                 discharge_efficiency: float = 0.95, min_state_of_charge: float = 0.1,
                 price_threshold_factor: float = 1.05, # Reduced from 1.1 to be more aggressive
                 max_cycle_fraction: float = 0.4):    # New parameter for max capacity per time interval
        self.battery_capacity = battery_capacity
        self.enable_grid_arbitrage = enable_grid_arbitrage
        self.enable_solar_arbitrage = enable_solar_arbitrage
        self.charge_efficiency = charge_efficiency  # Energy retained during charging (0.95 = 95%)
        self.discharge_efficiency = discharge_efficiency  # Energy available during discharge
        self.min_state_of_charge = min_state_of_charge  # Minimum battery level (percentage)
        self.price_threshold_factor = price_threshold_factor  # Factor to determine if storing solar is profitable
        self.max_cycle_fraction = max_cycle_fraction  # Max % of battery capacity per time interval (15min)
        
        # Efficiency factor combines both charge and discharge efficiency
        self.combined_efficiency = self.charge_efficiency * self.discharge_efficiency
        
        # Store transaction history for debugging/analytics
        self.transactions = []

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

        # Create a pivot table with both return and supply in one DataFrame
        energy_pivot = pd.pivot_table(
            energy_usage, 
            values='value',
            index=['timestamp', 'date'],
            columns='type',
            aggfunc='sum',
            fill_value=0
        ).reset_index()
        
        # Ensure both 'return' and 'supply' columns exist
        if 'return' not in energy_pivot.columns:
            energy_pivot['return'] = 0
        if 'supply' not in energy_pivot.columns:
            energy_pivot['supply'] = 0
            
        # Add energy prices to the pivot table
        energy_pivot = pd.merge(
            energy_pivot,
            energy_prices[['timestamp', 'price']],
            on='timestamp',
            how='left'
        )
        
        # Sort by timestamp to process chronologically
        energy_pivot = energy_pivot.sort_values('timestamp')
        
        # Calculate time intervals to determine max power per interval
        interval_minutes = self._determine_interval_minutes(energy_pivot)
        
        # Calculate max power (kW) based on max_cycle_fraction and interval
        # Scale by interval - if 15min intervals, we can use 25% of max_cycle_fraction per interval
        interval_fraction = interval_minutes / 60.0  # Convert to fraction of an hour
        max_power_per_interval = (self.battery_capacity * self.max_cycle_fraction * interval_fraction)
        
        # Battery constraints
        min_battery_level = self.battery_capacity * self.min_state_of_charge
        max_battery_level = self.battery_capacity
        current_battery_level = min_battery_level  # Start with minimum battery level
        
        # Daily metrics
        daily_metrics = {}
        
        # Group data by date for date-based processing
        date_groups = energy_pivot.groupby('date')
        
        # Process each date to generate plans
        for date, day_data in date_groups:
            if date not in daily_metrics:
                daily_metrics[date] = {
                    'gross_savings': 0,
                    'lost_revenue': 0,
                    'grid_arbitrage_savings': 0
                }
                
            # Create battery operation plan for this day
            solar_plan = {}
            grid_plan = {}
            
            # Plan for solar arbitrage (if enabled)
            if self.enable_solar_arbitrage:
                solar_plan = self._plan_solar_arbitrage(day_data, max_power_per_interval)
            
            # Plan for grid arbitrage (if enabled)
            if self.enable_grid_arbitrage:
                grid_plan = self._plan_grid_arbitrage(day_data, max_power_per_interval)
            
            # Execute the plans with updated battery state tracking
            for idx, row in day_data.iterrows():
                timestamp = row['timestamp']
                current_price = row['price']
                solar_return = row['return']  
                house_consumption = row['supply']
                net_energy = solar_return - house_consumption
                
                # Initial values
                solar_to_battery = 0
                solar_to_grid = 0 
                grid_to_battery = 0
                battery_to_house = 0
                battery_to_grid = 0
                grid_to_house = 0
                
                # Track actions for this timestamp
                actions = []
                
                # Execute solar arbitrage if enabled and planned
                if self.enable_solar_arbitrage and timestamp in solar_plan:
                    action = solar_plan[timestamp]
                    
                    if action['type'] == 'charge' and net_energy > 0:
                        # Store excess solar in battery
                        available_solar = net_energy
                        space_in_battery = (max_battery_level - current_battery_level) / self.charge_efficiency
                        charge_amount = min(available_solar, action['amount'], space_in_battery)
                        
                        if charge_amount > 0:
                            solar_to_battery = charge_amount
                            current_battery_level += charge_amount * self.charge_efficiency
                            daily_metrics[date]['lost_revenue'] += charge_amount * current_price
                            actions.append('solar_to_battery')
                            
                        # Remaining solar goes to grid
                        solar_to_grid = available_solar - solar_to_battery
                        
                    elif action['type'] == 'discharge' and net_energy < 0:
                        # Use battery to meet house demand
                        energy_needed = abs(net_energy)
                        available_battery = (current_battery_level - min_battery_level) * self.discharge_efficiency
                        discharge_amount = min(energy_needed, action['amount'], available_battery)
                        
                        if discharge_amount > 0:
                            battery_to_house = discharge_amount
                            current_battery_level -= discharge_amount / self.discharge_efficiency
                            daily_metrics[date]['gross_savings'] += discharge_amount * current_price
                            actions.append('battery_to_house')
                            
                        # Remaining deficit from grid
                        grid_to_house = energy_needed - battery_to_house
                    
                else:
                    # No solar arbitrage - default behavior
                    if net_energy > 0:
                        solar_to_grid = net_energy
                    else:
                        grid_to_house = abs(net_energy)
                
                # Execute grid arbitrage if enabled and planned
                if self.enable_grid_arbitrage and timestamp in grid_plan:
                    action = grid_plan[timestamp]
                    
                    if action['type'] == 'charge':
                        # Buy from grid to charge battery
                        space_in_battery = (max_battery_level - current_battery_level) / self.charge_efficiency
                        charge_amount = min(action['amount'], space_in_battery, max_power_per_interval)
                        
                        if charge_amount > 0:
                            grid_to_battery = charge_amount
                            current_battery_level += charge_amount * self.charge_efficiency
                            actions.append('grid_to_battery')
                            # Cost is tracked when we sell
                            
                    elif action['type'] == 'discharge':
                        # Sell from battery to grid
                        available_battery = (current_battery_level - min_battery_level) * self.discharge_efficiency
                        discharge_amount = min(action['amount'], available_battery, max_power_per_interval)
                        
                        if discharge_amount > 0:
                            battery_to_grid = discharge_amount
                            current_battery_level -= discharge_amount / self.discharge_efficiency
                            actions.append('battery_to_grid')
                            
                            # Calculate arbitrage profit
                            if 'buy_price' in action:
                                # Calculate effective buy amount accounting for efficiency losses
                                effective_buy_amount = discharge_amount / self.combined_efficiency
                                cost_to_buy = effective_buy_amount * action['buy_price']
                                revenue_from_sell = discharge_amount * current_price
                                
                                arbitrage_profit = revenue_from_sell - cost_to_buy
                                daily_metrics[date]['grid_arbitrage_savings'] += arbitrage_profit
                
                # Record this transaction
                self.transactions.append({
                    'timestamp': timestamp,
                    'date': date,
                    'price': current_price,
                    'solar_return': solar_return,
                    'house_consumption': house_consumption,
                    'net_energy': net_energy,
                    'solar_to_battery': solar_to_battery,
                    'solar_to_grid': solar_to_grid,
                    'grid_to_battery': grid_to_battery,
                    'battery_to_house': battery_to_house,
                    'battery_to_grid': battery_to_grid,
                    'grid_to_house': grid_to_house,
                    'battery_level': current_battery_level,
                    'actions': '+'.join(actions) if actions else 'none'
                })
        
        # Convert daily metrics to results format
        results = []
        for date, metrics in daily_metrics.items():
            if metrics['gross_savings'] > 0 or metrics['lost_revenue'] > 0 or metrics['grid_arbitrage_savings'] > 0:
                results.append({
                    'timestamp': date,
                    'gross_savings': metrics['gross_savings'],
                    'lost_revenue': metrics['lost_revenue'],
                    'net_savings': metrics['gross_savings'] - metrics['lost_revenue'],
                    'grid_arbitrage_savings': metrics['grid_arbitrage_savings']
                })
        
        if results:
            total_savings = pd.DataFrame(results)
            
            # Store battery operations data for analysis
            self.battery_operations = pd.DataFrame(self.transactions)
        
        return total_savings
    
    def _determine_interval_minutes(self, data):
        """Determine the time interval between data points in minutes."""
        if len(data) < 2:
            return 60  # Default to 1 hour if not enough data
        
        # Calculate the most common time difference
        timestamps = data['timestamp'].sort_values()
        time_diffs = timestamps.diff().dropna()
        
        if len(time_diffs) == 0:
            return 60
        
        # Convert to minutes and find most common
        minutes_diffs = time_diffs.dt.total_seconds() / 60
        most_common_diff = minutes_diffs.mode()[0]
        
        return most_common_diff
    
    def _plan_solar_arbitrage(self, day_data, max_power_per_interval):
        """
        Plan solar arbitrage strategy for the day.
        Decide when to store excess solar and when to use stored energy.
        
        Returns a dict of {timestamp: {'type': 'charge'/'discharge', 'amount': value}}
        """
        solar_plan = {}
        
        # Calculate daily price stats to make smarter decisions
        prices = day_data['price'].values
        avg_price = day_data['price'].mean()
        median_price = day_data['price'].median()
        price_std = day_data['price'].std()
        max_price = day_data['price'].max()
        min_price = day_data['price'].min()
        
        # Price thresholds for charging and discharging
        # More aggressive thresholds than before
        # Account for efficiency losses in thresholds
        required_price_increase = 1 / self.combined_efficiency
        
        # Define charge threshold 
        charge_threshold = min(
            avg_price,  # Below average price
            avg_price - 0.5 * price_std  # Or below average minus half std deviation
        )
        
        # Define discharge threshold
        discharge_threshold = max(
            avg_price * required_price_increase,  # Above efficiency-adjusted average
            avg_price + 0.5 * price_std,  # Or above average plus half std deviation
            charge_threshold * required_price_increase * self.price_threshold_factor  # Or minimum profitable threshold
        )
        
        # Analyze each timestamp to plan solar arbitrage
        for idx, row in day_data.iterrows():
            timestamp = row['timestamp']
            current_price = row['price']
            solar_return = row['return']
            house_consumption = row['supply']
            net_energy = solar_return - house_consumption
            
            if net_energy > 0 and current_price < charge_threshold:
                # Excess solar production during low-price period - charge battery
                solar_plan[timestamp] = {
                    'type': 'charge',
                    'amount': min(net_energy, max_power_per_interval),
                    'price': current_price
                }
            elif net_energy < 0 and current_price > discharge_threshold:
                # Energy deficit during high-price period - discharge battery
                solar_plan[timestamp] = {
                    'type': 'discharge',
                    'amount': min(abs(net_energy), max_power_per_interval),
                    'price': current_price
                }
        
        return solar_plan
    
    def _plan_grid_arbitrage(self, day_data, max_power_per_interval):
        """
        Plan grid arbitrage strategy for the day.
        Identify profitable buy-sell pairs across the day.
        
        Returns a dict of {timestamp: {'type': 'charge'/'discharge', 'amount': value, 'buy_price': buy_price}}
        """
        grid_plan = {}
        
        # Create a list of (timestamp, price) pairs and sort by price
        price_data = [(row['timestamp'], row['price']) for idx, row in day_data.iterrows()]
        
        # Sort first by price to identify arbitrage opportunities
        price_data_sorted = sorted(price_data, key=lambda x: x[1])
        
        # Required price difference to account for efficiency losses
        min_price_ratio = 1 / self.combined_efficiency
        
        # Find arbitrage opportunities using a more comprehensive approach
        buy_opportunities = []
        sell_opportunities = []
        
        # First identify all potential buy (low price) and sell (high price) points
        for i, (timestamp, price) in enumerate(price_data_sorted):
            if i < len(price_data_sorted) // 3:  # Lowest third of prices - potential buys
                buy_opportunities.append((timestamp, price))
            elif i >= 2 * len(price_data_sorted) // 3:  # Highest third of prices - potential sells
                sell_opportunities.append((timestamp, price))
        
        # Sort buy/sell opportunities by timestamp
        buy_opportunities.sort(key=lambda x: x[0])
        sell_opportunities.sort(key=lambda x: x[0])
        
        # Create buy/sell pairs that respect time ordering
        arbitrage_pairs = []
        
        for buy_ts, buy_price in buy_opportunities:
            # Find sell opportunities that come after this buy
            future_sells = [(sell_ts, sell_price) for sell_ts, sell_price in sell_opportunities if sell_ts > buy_ts]
            
            for sell_ts, sell_price in future_sells:
                # Check if price ratio is profitable
                if sell_price > buy_price * min_price_ratio * self.price_threshold_factor:
                    # Profitable opportunity
                    profit_per_unit = sell_price - (buy_price / self.combined_efficiency)
                    arbitrage_pairs.append((buy_ts, buy_price, sell_ts, sell_price, profit_per_unit))
        
        # Sort pairs by profitability
        arbitrage_pairs.sort(key=lambda x: x[4], reverse=True)
        
        # Allocate battery capacity to most profitable pairs first
        # We'll need to track capacity already allocated at each timestamp
        allocated_capacity = {row['timestamp']: 0 for idx, row in day_data.iterrows()}
        
        for buy_ts, buy_price, sell_ts, sell_price, profit in arbitrage_pairs:
            # Check remaining capacity at both timestamps
            buy_remaining = max_power_per_interval - allocated_capacity.get(buy_ts, 0)
            sell_remaining = max_power_per_interval - allocated_capacity.get(sell_ts, 0)
            
            if buy_remaining > 0 and sell_remaining > 0:
                # Determine amount for this arbitrage pair
                amount = min(buy_remaining, sell_remaining)
                
                # Record in grid plan
                if buy_ts not in grid_plan:
                    grid_plan[buy_ts] = {
                        'type': 'charge',
                        'amount': amount,
                        'price': buy_price
                    }
                else:
                    grid_plan[buy_ts]['amount'] += amount
                
                if sell_ts not in grid_plan:
                    grid_plan[sell_ts] = {
                        'type': 'discharge',
                        'amount': amount,
                        'price': sell_price,
                        'buy_price': buy_price
                    }
                else:
                    grid_plan[sell_ts]['amount'] += amount
                    # If multiple buy prices, use weighted average
                    if 'buy_price' in grid_plan[sell_ts]:
                        prev_amount = grid_plan[sell_ts]['amount'] - amount
                        prev_buy_price = grid_plan[sell_ts]['buy_price']
                        grid_plan[sell_ts]['buy_price'] = (prev_buy_price * prev_amount + buy_price * amount) / grid_plan[sell_ts]['amount']
                
                # Update allocated capacity
                allocated_capacity[buy_ts] += amount
                allocated_capacity[sell_ts] += amount
        
        return grid_plan




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
    bm = BatterySavingsCalculator(enable_grid_arbitrage=True, battery_capacity=200.0)
    bm.arbitrage(usage_df, price)


