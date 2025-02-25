import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
from typing import Literal, Dict, List
import streamlit as st
from functools import lru_cache
import concurrent.futures

class KenterAPI:
    """Simple Kenter API client for retrieving energy data."""
    
    def __init__(self, connection_id=None, metering_point=None):
        self._client_id = "api_132304_f4a7ac"
        self._client_secret = st.secrets["KENTER_CLIENT_SECRET"]
        self._connection_id = connection_id
        self._metering_point = metering_point
        self._base_url = "https://api.kenter.nu/meetdata/v2"
        self._token_url = "https://login.kenter.nu/connect/token"
        self._token = None
        self._token_expiry = None
        self._cache = {}

    def _get_token(self) -> str:
        """Get authentication token with caching."""
        # Check if token is still valid (with 5 min margin)
        if self._token and self._token_expiry and datetime.now() < self._token_expiry - timedelta(minutes=5):
            return self._token

        payload = {
            'client_id': self._client_id,
            'client_secret': self._client_secret,
            'grant_type': 'client_credentials',
            'scope': 'meetdata.read'
        }
        response = requests.post(
            self._token_url, 
            data=payload, 
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        response.raise_for_status()
        token_data = response.json()
        self._token = token_data['access_token']
        # Set token expiry (usually 1 hour)
        self._token_expiry = datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600))
        return self._token

    @lru_cache(maxsize=128)
    def _get_day_data(self, date: datetime) -> dict:
        """Get energy data for specific date with caching."""
        cache_key = f"{self._connection_id}_{self._metering_point}_{date.strftime('%Y-%m-%d')}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self._token:
            self._token = self._get_token()
            
        url = f"{self._base_url}/measurements/connections/{self._connection_id}/metering-points/{self._metering_point}/days/{date.year}/{date.month:02d}/{date.day:02d}"
        response = requests.get(url, headers={'Authorization': f'Bearer {self._token}'})
        
        # Handle token expiration
        if response.status_code == 401:
            self._token = self._get_token()
            response = requests.get(url, headers={'Authorization': f'Bearer {self._token}'})
            
        response.raise_for_status()
        data = response.json()
        self._cache[cache_key] = data
        return data
    
    def get_meter_list(self) -> list:
        """Retrieve all available connections and metering points."""
        if not self._token:
            self._token = self._get_token()
        
        url = f"{self._base_url}/meters"
        response = requests.get(url, headers={'Authorization': f'Bearer {self._token}'})
        response.raise_for_status()
        
        return response.json()

    def get_gtv_info(self) -> Dict[str, Dict]:
        """
        Extract GTV (Gecontracteerd Transportvermogen) information for all connections.
        
        Returns:
            Dict with connection IDs as keys and dict containing GTV and location info as values
        """
        meter_data = self.get_meter_list()
        gtv_info = {}
        
        for connection in meter_data:
            conn_id = connection.get('connectionId')
            if not conn_id:
                continue
                
            # Get all metering points' master data to find GTV
            gtv_found = False
            if connection.get('meteringPoints'):
                for mp in connection['meteringPoints']:
                    master_data_list = mp.get('masterData', [])
                    for master_data in master_data_list:
                        if master_data.get('contractedCapacity'):
                            gtv_found = True
                            gtv_info[conn_id] = {
                                'gtv': master_data.get('contractedCapacity'),
                                'address': master_data.get('address'),
                                'city': master_data.get('city'),
                                'bp_code': master_data.get('bpCode'),
                                'bp_name': master_data.get('bpName')
                            }
                            break
                    if gtv_found:
                        break
                
                # If no GTV found in any metering point, use first metering point's data
                if not gtv_found:
                    master_data = connection['meteringPoints'][0].get('masterData', [{}])[0]
                    gtv_info[conn_id] = {
                        'gtv': 'N/A',
                        'address': master_data.get('address'),
                        'city': master_data.get('city'),
                        'bp_code': master_data.get('bpCode'),
                        'bp_name': master_data.get('bpName')
                    }
        
        return gtv_info

def get_kenter_data(
    start_date: str, 
    end_date: str, 
    connection_id: str,  # New parameter
    metering_point: str,  # New parameter
    interval: Literal['15min', '1h'] = '15min'
) -> pd.DataFrame:
    """
    Get Kenter energy data for supply and return.
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        interval: Time interval ('15min' or '1h', default: '15min')
        
    Returns:
        DataFrame with energy data at specified interval
        
    Raises:
        ValueError: If date range exceeds 1 year or invalid interval
    """
    # Validate interval
    if interval not in ['15min', '1h']:
        raise ValueError("Interval must be '15min' or '1h'")
    
    # Convert dates
    tz = pytz.timezone('Europe/Amsterdam')
    # start = tz.localize(datetime.strptime(start_date, '%Y-%m-%d'))
    # get one day before the selected time, since entsoe retrieves from 00:15 and we need from 00:00
    start = pd.Timestamp(start_date, tz='Europe/Amsterdam') - pd.Timedelta(days=1)

    end = tz.localize(datetime.strptime(end_date, '%Y-%m-%d'))
    
    # Validate date range
    if (end - start).days > 365:
        raise ValueError("Date range cannot exceed 1 year")
        
    # Initialize API
    api = KenterAPI(connection_id=connection_id, metering_point=metering_point)
    channels = {'16180': 'supply', '16280': 'return'}
    
    # Generate list of dates to fetch
    dates = pd.date_range(start=start, end=end, freq='D')
    
    # Fetch data in parallel
    data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_date = {executor.submit(api._get_day_data, date): date for date in dates}
        for future in concurrent.futures.as_completed(future_to_date):
            day_data = future.result()
            for channel in day_data:
                if channel['channelId'] in channels:
                    for measurement in channel.get('Measurements', []):
                        timestamp = datetime.fromtimestamp(
                            measurement['timestamp'], 
                            tz=pytz.UTC
                        ).astimezone(tz).replace(tzinfo=None)
                        
                        data.append({
                            'timestamp': timestamp,
                            'value': measurement['value'],
                            'type': channels[channel['channelId']]
                        })
    
    # Create DataFrame efficiently
    df = pd.DataFrame(data)
    
    if interval == '15min':
        # Filter data to start from the specified start_date at 00:00
        start_datetime = pd.Timestamp(start_date, tz='Europe/Amsterdam').replace(tzinfo=None)
        df = df[df['timestamp'] >= start_datetime]
        
        # Optimize pivot operations
        df = (df.groupby(['timestamp', 'type'])['value']
              .mean()
              .unstack(fill_value=0)
              .reset_index())
        
        # Ensure all required columns exist
        for col in ['supply', 'return']:
            if col not in df.columns:
                df[col] = 0
                
        # Melt back to long format efficiently
        df = df.melt(
            id_vars=['timestamp'],
            value_vars=['supply', 'return'],
            var_name='type',
            value_name='value'
        )
        
        return df.iloc[:-1]  # remove very last 00:00
        
    elif interval == '1h':
        # Optimize hourly resampling
        pivot_df = (df.pivot(index='timestamp', columns='type', values='value')
                   .resample('1H')
                   .sum()
                   .reset_index())
        
        return (pivot_df.melt(
            id_vars=['timestamp'],
            value_vars=['supply', 'return'],
            var_name='type',
            value_name='value'
        ).sort_values('timestamp')
         .reset_index(drop=True))