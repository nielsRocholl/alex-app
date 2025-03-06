from typing import Dict, Literal, Optional
import pandas as pd
from datetime import time
import holidays

class NetworkTaxCalculator:
    """Calculator for network operator specific energy taxes."""
    
    NETWORK_OPERATORS = ["Enexis"]  # Add more operators as needed
    
    # Tax rates per operator (in cents/kWh)
    TAX_RATES = {
        "Enexis": {
            "low_gtv": {  # < 50 kW
                "normal": 8.04,
                "low": 4.21
            },
            "high_gtv": {  # >= 50 kW
                "normal": 2.50,
                "low": 2.50
            }
        }
    }
    
    @staticmethod
    def get_tax_rate(operator: str, gtv: float, rate_type: Literal["normal", "low"]) -> float:
        """
        Get the appropriate tax rate based on operator, GTV, and rate type.
        
        Args:
            operator: Network operator name
            gtv: Contracted capacity in kW
            rate_type: Type of rate ("normal" or "low")
            
        Returns:
            Tax rate in cents/kWh
        """
        if operator not in NetworkTaxCalculator.TAX_RATES:
            raise ValueError(f"Unknown network operator: {operator}")
            
        # For now, only implement Enexis logic
        if operator == "Enexis":
            gtv_category = "low_gtv" if gtv < 50 else "high_gtv"
            return NetworkTaxCalculator.TAX_RATES[operator][gtv_category][rate_type]
        
        return 0.0
    
    @staticmethod
    def determine_rate_type(timestamp) -> str:
        """
        Determine the rate type based on the timestamp.
        
        Normal rate: working days 7:00 AM - 11:00 PM
        Low rate: working days 11:00 PM - 7:00 AM
        Low rate: All day on weekends and public holidays
        
        Args:
            timestamp: The timestamp to evaluate
            
        Returns:
            rate_type: "normal" or "low"
        """
        # Convert to pandas Timestamp if not already
        ts = pd.Timestamp(timestamp)
        
        # Check if it's a weekend (Saturday = 5, Sunday = 6)
        if ts.dayofweek >= 5:
            return "low"
        
        # Check if it's a holiday in the Netherlands
        nl_holidays = holidays.NL()
        if ts.date() in nl_holidays:
            return "low"
        
        # Check time of day
        ts_time = ts.time()
        morning_start = time(7, 0)  # 7:00 AM
        night_start = time(23, 0)   # 11:00 PM
        
        if morning_start <= ts_time < night_start:
            return "normal"
        else:
            return "low"
    
    @staticmethod
    def calculate_tax(
        usage_df: pd.DataFrame,
        operator: str,
        gtv: float,
        rate_schedule: Optional[Dict[pd.Timestamp, str]] = None
    ) -> pd.DataFrame:
        """
        Calculate network tax for energy consumption.
        
        Args:
            usage_df: DataFrame with columns [timestamp, type, value]
            operator: Network operator name
            gtv: Contracted capacity in kW
            rate_schedule: Optional dict mapping timestamps to rate types ("normal" or "low")
                         If None, determines rate types based on time of day rules
        
        Returns:
            DataFrame with tax calculations
        """
        # Only calculate tax for energy drawn from grid (supply)
        supply_df = usage_df[usage_df['type'] == 'supply'].copy()
        
        if rate_schedule is None:
            # Determine rate type based on timestamp
            supply_df['rate_type'] = supply_df['timestamp'].apply(
                NetworkTaxCalculator.determine_rate_type
            )
        else:
            # Assign rate type based on provided schedule
            supply_df['rate_type'] = supply_df['timestamp'].map(
                lambda x: rate_schedule.get(pd.Timestamp(x), 'normal')
            )
        
        # Calculate tax for each row
        supply_df['tax_rate'] = supply_df['rate_type'].apply(
            lambda x: NetworkTaxCalculator.get_tax_rate(operator, gtv, x)
        )
        
        # Convert tax rate from cents/kWh to euros/kWh
        supply_df['tax_amount'] = supply_df['value'] * (supply_df['tax_rate'] / 100)
        
        return supply_df[['timestamp', 'value', 'rate_type', 'tax_rate', 'tax_amount']] 