import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
from typing import Literal, Dict, List
import streamlit as st

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

    def _get_token(self) -> str:
        """Get authentication token."""
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
        return response.json()['access_token']

    def _get_day_data(self, date: datetime) -> dict:
        """Get energy data for specific date."""
        if not self._token:
            self._token = self._get_token()
            
        url = f"{self._base_url}/measurements/connections/{self._connection_id}/metering-points/{self._metering_point}/days/{date.year}/{date.month:02d}/{date.day:02d}"
        response = requests.get(url, headers={'Authorization': f'Bearer {self._token}'})
        response.raise_for_status()
        return response.json()
    
    def get_meter_list(self) -> list:
        """Retrieve all available connections and metering points."""
        if not self._token:
            self._token = self._get_token()
        
        url = f"{self._base_url}/meters"
        response = requests.get(url, headers={'Authorization': f'Bearer {self._token}'})
        response.raise_for_status()
        
        return response.json()


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
        
    # Initialize API and data collection
    api = KenterAPI(connection_id=connection_id, metering_point=metering_point)
    data = []
    channels = {'16180': 'supply', '16280': 'return'}
    current_date = start
    
    # Collect data
    while current_date <= end:
        day_data = api._get_day_data(current_date)
        
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
        
        current_date += timedelta(days=1)
    
    # Create DataFrame
    df = pd.DataFrame(data)
    
    # If hourly interval is requested, resample the data
    if interval == '15min':
        # Filter data to start from the specified start_date at 00:00
        start_datetime = pd.Timestamp(start_date, tz='Europe/Amsterdam').replace(tzinfo=None)
        df = df[df['timestamp'] >= start_datetime]
        
        # Pivot and sort the data
        df = df.pivot(index='timestamp', columns='type', values='value').reset_index()
        df = df.sort_values('timestamp')
        
        # Melt back to long format
        df = df.melt(
            id_vars=['timestamp'],
            value_vars=['supply', 'return'],
            var_name='type',
            value_name='value'
        )
        
        # remove very last 00:00
        df = df.iloc[:-1]
        return df
    elif interval == '1h':
        # Pivot the data first
        df_pivot = df.pivot(index='timestamp', columns='type', values='value')
        
        # Resample to hourly data
        df_hourly = df_pivot.resample('1H').sum()
        
        # Reset the format back to match 15-min data structure
        df = pd.DataFrame({
            'timestamp': df_hourly.index,
            'supply': df_hourly['supply'],
            'return': df_hourly['return']
        }).melt(
            id_vars=['timestamp'],
            value_vars=['supply', 'return'],
            var_name='type',
            value_name='value'
        )
        return df.sort_values('timestamp').reset_index(drop=True)