import pandas as pd
from entsoe import EntsoePandasClient
from datetime import datetime
import pytz

class EntsoeAPI:
    """Simple ENTSO-E API client for retrieving energy prices."""
    
    def __init__(self):
        self._api_key = "5ced150d-c502-4143-864b-321e875ae021"
        self._client = EntsoePandasClient(api_key=self._api_key)

    def _get_prices(self, start: datetime, end: datetime, country_code: str) -> pd.Series:
        """Get day-ahead prices from ENTSO-E."""
        return self._client.query_day_ahead_prices(country_code, start=start, end=end)

def get_energy_prices(start_date: str, end_date: str, country_code: str = 'NL', interval: str = '15min') -> pd.DataFrame:
    """
    Get ENTSO-E energy prices for specified period with 1h/15-minute intervals.
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        country_code: Country code (default: 'NL' for Netherlands)
        interval: chose interval
        
    Returns:
        DataFrame with 1h/15-minute interval energy prices in EUR/kWh
    """
    # Convert dates to timezone-aware pandas timestamps
    start = pd.Timestamp(start_date, tz='Europe/Amsterdam')
    end = pd.Timestamp(end_date, tz='Europe/Amsterdam')
    
    # Add one day to end date to get full day
    end = end + pd.Timedelta(days=1)
    
    # Validate date range
    if (end - start).days > 365:
        raise ValueError("Date range cannot exceed 1 year")
    
    # Get price data
    api = EntsoeAPI()
    prices = api._get_prices(start, end, country_code)
    
    # Convert to DataFrame
    df = pd.DataFrame({
        'timestamp': prices.index.tz_localize(None),  # Remove timezone info
        'price': prices.values / 1000  # Convert from EUR/MWh to EUR/kWh
    })
    
    if interval == '1h':
        return df
    else:
        df.set_index('timestamp', inplace=True)
        
        # Create 15-min index starting at 00:15
        new_index = pd.date_range(
            start=df.index[0],
            end=df.index[-1] + pd.Timedelta(hours=1),  # Add 1 hour to include next day's first value
            freq='15min',
            inclusive='left'  # Exclude the last timestamp
        )
        
        # Reindex using forward fill
        df_15min = df.reindex(new_index, method='ffill')
        df_15min.reset_index(inplace=True)
        df_15min.rename(columns={'index': 'timestamp'}, inplace=True)
        
        return df_15min


if __name__ == "__main__":
    # Fetch data for January 14th, 2025
    date = '2025-01-14'
    prices_df = get_energy_prices(date, date)

    # Save to CSV
    output_file = 'energy_prices_20250114.csv'
    prices_df.to_csv(output_file, index=False)

    print(f"Data saved to {output_file}")
    print(f"\nFirst few rows of data:")
    print(prices_df.head())