from typing import Dict, Literal, Optional
import pandas as pd

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
                         If None, assumes normal rate for all times
        
        Returns:
            DataFrame with tax calculations
        """
        # Only calculate tax for energy drawn from grid (supply)
        supply_df = usage_df[usage_df['type'] == 'supply'].copy()
        
        if rate_schedule is None:
            # Use normal rate for all times if no schedule provided
            supply_df['rate_type'] = 'normal'
        else:
            # Assign rate type based on schedule
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