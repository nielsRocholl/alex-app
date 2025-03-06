import pandas as pd
import numpy as np
from typing import Dict, Tuple, List
from modules.kenter_module import *
from modules.entsoe_module import *

class BatterySavingsCalculator:
    """Calculator for potential savings using battery storage system."""
    
    def __init__(self, battery_capacity: float = 100.0, 
                 enable_solar_arbitrage: bool = True, charge_efficiency: float = 0.95, 
                 discharge_efficiency: float = 0.95, min_state_of_charge: float = 0.1,
                 price_threshold_factor: float = 1.05, # Factor to determine if storing solar is profitable
                 max_cycle_fraction: float = 1.0,    # For large commercial batteries, 1C is more realistic
                 maximum_charge_rate_kw: float = None):    # Will be automatically calculated based on capacity
        self.battery_capacity = battery_capacity
        self.enable_solar_arbitrage = enable_solar_arbitrage
        self.charge_efficiency = charge_efficiency  # Energy retained during charging (0.95 = 95%)
        self.discharge_efficiency = discharge_efficiency  # Energy available during discharge
        self.min_state_of_charge = min_state_of_charge  # Minimum battery level (percentage)
        self.price_threshold_factor = price_threshold_factor  # Factor to determine if storing solar is profitable
        self.max_cycle_fraction = max_cycle_fraction  # Max % of battery capacity per time interval (15min)
        
        # Auto-calculate maximum charge rate based on battery size if not provided
        # Large commercial batteries typically have more powerful inverters
        if maximum_charge_rate_kw is None:
            if battery_capacity < 50:  # Small residential
                self.maximum_charge_rate_kw = min(10.0, battery_capacity * 0.5)  # 5-10kW typical
            elif battery_capacity < 100:  # Large residential/small commercial
                self.maximum_charge_rate_kw = min(50.0, battery_capacity * 0.7)  # Up to 50kW
            elif battery_capacity < 250:  # Medium commercial
                self.maximum_charge_rate_kw = min(100.0, battery_capacity * 0.8)  # Up to 100kW
            else:  # Large commercial/farm
                self.maximum_charge_rate_kw = min(250.0, battery_capacity * 0.9)  # Up to 250kW
        else:
            self.maximum_charge_rate_kw = maximum_charge_rate_kw
        
        # Efficiency factor combines both charge and discharge efficiency
        self.combined_efficiency = self.charge_efficiency * self.discharge_efficiency
        
        # Store transaction history for debugging/analytics
        self.transactions = []
        # Track the source of energy (for tax purposes)
        self.battery_solar_percentage = 0.0  # Track percentage of battery energy from solar

    def arbitrage(self, energy_usage: pd.DataFrame, energy_prices: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        Calculate potential savings through arbitrage using battery storage.

        Args:
            energy_usage: DataFrame with columns [timestamp, type, value]
                where type is either 'return' or 'supply'
            energy_prices: DataFrame with columns [timestamp, price]

        Returns:
            Dict with keys:
                'savings': DataFrame with total potential savings
                'energy_flows': DataFrame with detailed energy flows by source
        """
        # Initialize result DataFrame
        total_savings = pd.DataFrame({
            'timestamp': pd.Series(dtype='datetime64[ns]'),
            'gross_savings': pd.Series(dtype='float64'),
            'lost_revenue': pd.Series(dtype='float64'),
            'net_savings': pd.Series(dtype='float64'),
            'grid_arbitrage_savings': pd.Series(dtype='float64')
        })
        
        if not self.enable_solar_arbitrage:
            return {'savings': total_savings, 'energy_flows': pd.DataFrame()}

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
        
        # Calculate max power (kW) based on both percentage and absolute limits
        # Scale by interval - if 15min intervals, we can use 25% of max_cycle_fraction per interval
        interval_fraction = interval_minutes / 60.0  # Convert to fraction of an hour
        
        # 1. Percentage-based limit (as a fraction of total capacity)
        percentage_limit = self.battery_capacity * self.max_cycle_fraction * interval_fraction
        
        # 2. Absolute power limit (scaled for the interval)
        absolute_limit = self.maximum_charge_rate_kw * interval_fraction
        
        # Use the more conservative (lower) of the two limits
        max_power_per_interval = min(percentage_limit, absolute_limit)
        
        # Add informative comment about the charging rate limit
        charging_rate_explanation = f"Charging limited to {max_power_per_interval:.2f} kWh per {interval_minutes:.0f}-minute interval"
        charging_rate_explanation += f" ({self.maximum_charge_rate_kw:.1f} kW inverter, {self.max_cycle_fraction:.1f}C battery rate)"
        
        # Battery constraints
        min_battery_level = self.battery_capacity * self.min_state_of_charge
        max_battery_level = self.battery_capacity
        current_battery_level = min_battery_level  # Start with minimum battery level
        
        # Track battery composition - assume initial charge is from solar
        solar_energy_in_battery = min_battery_level
        grid_energy_in_battery = 0.0
        
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
                    'grid_arbitrage_savings': 0,
                    'charge_rate_info': charging_rate_explanation
                }
                
            # Create battery operation plan for this day
            solar_plan = {}
            
            # Plan for solar arbitrage
            if self.enable_solar_arbitrage:
                solar_plan = self._plan_solar_arbitrage(day_data, max_power_per_interval)
            
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
                
                # New fields to track energy sources for tax purposes
                solar_origin_to_house = 0  # Energy from solar (direct or via battery)
                grid_origin_to_house = 0   # Energy from grid (direct or via battery) 
                
                # Debug info
                charge_limited_by = "none"
                
                # Track actions for this timestamp
                actions = []
                
                # Execute solar arbitrage if enabled and planned
                if self.enable_solar_arbitrage and timestamp in solar_plan:
                    action = solar_plan[timestamp]
                    
                    if action['type'] == 'charge' and net_energy > 0:
                        # Store excess solar in battery
                        available_solar = net_energy
                        space_in_battery = (max_battery_level - current_battery_level) / self.charge_efficiency
                        
                        # Be more aggressive with solar charging - use higher of planned amount and max_power_per_interval
                        max_charging_rate = max(action['amount'], max_power_per_interval)
                        
                        # Apply charge tapering when battery is above 80% - reduces charge rate as battery fills
                        battery_percentage = current_battery_level / max_battery_level
                        if battery_percentage > 0.8:
                            # Linear taper from 100% charge rate at 80% SOC to 20% charge rate at 100% SOC
                            taper_factor = 1.0 - ((battery_percentage - 0.8) / 0.2) * 0.8
                            max_charging_rate *= taper_factor
                            charge_limited_by = "taper"
                        
                        # Final charge amount is limited by available solar, charging rate, and space in battery
                        charge_amount = min(available_solar, max_charging_rate, space_in_battery)
                        
                        # Debug info for tracking why some solar might go to grid
                        if charge_limited_by == "none" and charge_amount < available_solar:
                            if space_in_battery < available_solar:
                                charge_limited_by = "battery_space"
                            elif max_charging_rate < available_solar:
                                charge_limited_by = "charging_rate"
                        
                        if charge_amount > 0:
                            solar_to_battery = charge_amount
                            current_battery_level += charge_amount * self.charge_efficiency
                            # Update battery composition - add solar energy
                            solar_energy_in_battery += charge_amount * self.charge_efficiency
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
                            
                            # Calculate how much of this energy came from solar vs grid
                            # based on current battery composition
                            if current_battery_level > 0:
                                solar_percentage = solar_energy_in_battery / current_battery_level
                                grid_percentage = grid_energy_in_battery / current_battery_level
                                
                                # Update tracking for tax purposes
                                solar_from_battery = discharge_amount * solar_percentage
                                grid_from_battery = discharge_amount * grid_percentage
                                
                                solar_origin_to_house += solar_from_battery
                                grid_origin_to_house += grid_from_battery
                                
                                # Reduce battery energy by source
                                raw_discharge = discharge_amount / self.discharge_efficiency
                                solar_energy_in_battery -= raw_discharge * solar_percentage
                                grid_energy_in_battery -= raw_discharge * grid_percentage
                            else:
                                # Shouldn't happen but just in case
                                grid_origin_to_house += discharge_amount
                                
                            current_battery_level -= discharge_amount / self.discharge_efficiency
                            daily_metrics[date]['gross_savings'] += discharge_amount * current_price
                            actions.append('battery_to_house')
                            
                        # Remaining deficit from grid
                        grid_to_house = energy_needed - battery_to_house
                        grid_origin_to_house += grid_to_house  # Direct grid usage for tax
                    
                else:
                    # No solar arbitrage - default behavior
                    if net_energy > 0:
                        solar_to_grid = net_energy
                        solar_origin_to_house = 0
                    else:
                        grid_to_house = abs(net_energy)
                        grid_origin_to_house = grid_to_house  # Direct grid usage for tax
                
                # Record this transaction with enhanced source tracking
                transaction_data = {
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
                    'solar_energy_in_battery': solar_energy_in_battery,
                    'grid_energy_in_battery': grid_energy_in_battery,
                    'solar_origin_to_house': solar_origin_to_house,
                    'grid_origin_to_house': grid_origin_to_house,
                    'actions': '+'.join(actions) if actions else 'none',
                    'charge_limited_by': charge_limited_by
                }
                
                # Add charge rate info from daily metrics
                if 'charge_rate_info' in daily_metrics[date]:
                    transaction_data['charge_rate_info'] = daily_metrics[date]['charge_rate_info']
                
                self.transactions.append(transaction_data)
        
        # Convert daily metrics to results format
        results = []
        for date, metrics in daily_metrics.items():
            if metrics['gross_savings'] > 0 or metrics['lost_revenue'] > 0:
                results.append({
                    'timestamp': date,
                    'gross_savings': metrics['gross_savings'],
                    'lost_revenue': metrics['lost_revenue'],
                    'net_savings': metrics['gross_savings'] - metrics['lost_revenue'],
                    'grid_arbitrage_savings': 0  # Keep the column but set to zero
                })
        
        # Convert transactions to DataFrame for energy flow tracking
        energy_flows_df = pd.DataFrame(self.transactions)
        
        # Convert results to DataFrame
        if results:
            total_savings = pd.DataFrame(results)
            total_savings['timestamp'] = pd.to_datetime(total_savings['timestamp'])
            total_savings = total_savings.sort_values('timestamp')
        
        return {
            'savings': total_savings,
            'energy_flows': energy_flows_df
        }
    
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
            
            if net_energy > 0:
                # Always store excess solar energy in battery when available, regardless of price
                # This prioritizes self-consumption of solar over grid return
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
    bm = BatterySavingsCalculator(battery_capacity=200.0)
    bm.arbitrage(usage_df, price)


