import pandas as pd
from entsoe import EntsoePandasClient
from datetime import datetime
import streamlit as st
import time
from functools import lru_cache
import concurrent.futures

class EntsoeAPI:
    """Simple ENTSO-E API client for retrieving energy prices."""
    
    def __init__(self):
        self._api_key = st.secrets["ENTSOE_CLIENT_SECRET"] 
        self._client = EntsoePandasClient(api_key=self._api_key)
        self._cache = {}

    @lru_cache(maxsize=128)
    def _get_prices(self, start: datetime, end: datetime, country_code: str) -> pd.Series:
        """Get day-ahead prices from ENTSO-E with caching."""
        cache_key = f"{start}_{end}_{country_code}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            prices = self._client.query_day_ahead_prices(country_code, start=start, end=end)
            self._cache[cache_key] = prices
            return prices
        except Exception as e:
            # Log the error details
            print(f"Error fetching prices for period {start} to {end}: {str(e)}")
            return pd.Series()

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
    
    # Check if we're requesting future data
    now = pd.Timestamp.now(tz='Europe/Amsterdam')
    max_future = now + pd.Timedelta(days=30)
    
    if end > max_future:
        end = max_future
        print(f"Adjusted end date to maximum available future date: {end.date()}")
    
    # Get price data in parallel monthly chunks
    api = EntsoeAPI()
    chunks = []
    chunk_params = []
    
    current_start = start
    while current_start < end:
        # Calculate chunk end date (end of month or final end date)
        chunk_end = min(
            current_start + pd.offsets.MonthEnd(0),
            end
        )
        
        chunk_params.append((current_start, chunk_end, country_code))
        current_start = chunk_end + pd.Timedelta(days=1)
    
    # Fetch chunks in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(api._get_prices, start, end, cc)
            for start, end, cc in chunk_params
        ]
        chunks = [future.result() for future in futures if not future.result().empty]
    
    if not chunks:
        raise ValueError(f"No price data available for the period {start.date()} to {end.date()}")
    
    # Combine chunks and handle duplicates
    all_prices = pd.concat(chunks)
    all_prices = all_prices[~all_prices.index.duplicated(keep='first')]
    all_prices = all_prices.sort_index()
    
    if interval == '1h':
        # Convert to DataFrame with hourly data
        return pd.DataFrame({
            'timestamp': all_prices.index.tz_localize(None),
            'price': all_prices.values / 1000
        })
    
    # Create 15-minute interval timestamps
    start_time = all_prices.index[0].tz_localize(None)
    end_time = all_prices.index[-1].tz_localize(None)
    
    # Create timestamps for 15-minute intervals
    timestamps = pd.date_range(
        start=start_time,
        end=end_time,
        freq='15min',
        inclusive='right'
    )
    
    # Optimize 15-minute interval creation using vectorized operations
    result = pd.DataFrame({'timestamp': timestamps})
    result['hour'] = result['timestamp'].dt.floor('h')
    hourly_prices = pd.Series(all_prices.values / 1000, index=all_prices.index.tz_localize(None))
    result['price'] = result['hour'].map(dict(zip(hourly_prices.index, hourly_prices.values)))
    
    return result.drop('hour', axis=1).reset_index(drop=True)


if __name__ == "__main__":
    start = '2024-01-01'
    end = '2024-12-30'
    
    try:
        prices_df = get_energy_prices(start, end)
        
        # Save to CSV
        output_file = 'energy_prices_2024.csv'
        prices_df.to_csv(output_file, index=False)
        
        print(f"Data saved to {output_file}")
        print(f"\nFirst few rows of data:")
        print(prices_df.head())
        print(f"\nLast few rows of data:")
        print(prices_df.tail())
        
    except Exception as e:
        print(f"Error: {str(e)}")

