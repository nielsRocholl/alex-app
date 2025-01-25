from datetime import datetime
import plotly.graph_objects as go
import pandas as pd
import os



def is_running_on_localhost():
    host = os.getenv("STREAMLIT_SERVER_ADDRESS", "localhost")
    port = os.getenv("STREAMLIT_SERVER_PORT", "8501")
    return host == "localhost" and port == "8501"


def validate_dates(start_date, end_date):
    """Validate date range."""
    today = datetime.now().date()
    
    if start_date > end_date:
        return False, "Start date must be before end date"
    
    if end_date >= today or start_date >= today:
        return False, "Dates need to be before today"
    
    date_diff = end_date - start_date
    if date_diff.days > 365:
        return False, "Date range cannot exceed 1 year"
    
    return True, ""


def calculate_daily_costs(usage_df, price_df):
    """Calculate the daily energy costs."""
    # Ensure we're working with copies
    usage_df = usage_df.copy()
    price_df = price_df.copy()
    
    # Convert timestamps to datetime
    usage_df['timestamp'] = pd.to_datetime(usage_df['timestamp'])
    price_df['timestamp'] = pd.to_datetime(price_df['timestamp'])
    
    # Get only supply data
    supply_df = usage_df[usage_df['type'] == 'supply'].copy()
    
    # Merge with prices
    costs = pd.merge(supply_df, price_df[['timestamp', 'price']], on='timestamp', how='left')
    
    # Calculate cost per interval
    costs['cost'] = costs['value'] * costs['price']
    
    # Group by date
    costs['date'] = costs['timestamp'].dt.date
    daily_costs = costs.groupby('date')['cost'].sum().reset_index()
    
    return daily_costs


### PLOTTING FUNCTIONS ###


def create_plot(usage_df, price_df):
    """Create an improved plot for energy usage, return, and prices."""
    fig = go.Figure()

    # Add usage data
    for energy_type, color in [('supply', '#4CAF50'), ('return', '#FF9800')]:
        data = usage_df[usage_df['type'] == energy_type]
        fig.add_trace(go.Scatter(
            x=data['timestamp'],
            y=data['value'],
            name=f'{energy_type.title()} (kWh)',
            line=dict(color=color, width=2)
        ))

    # Add price data
    fig.add_trace(go.Scatter(
        x=price_df['timestamp'],
        y=price_df['price'],
        name='Price (EUR/kWh)',
        line=dict(color='#9C27B0', width=2, dash='dot'),
        yaxis='y2'
    ))

    # Update layout
    fig.update_layout(
        title='Energy Usage and Prices',
        xaxis_title='Date',
        yaxis=dict(title='Energy (kWh)', linecolor='#4CAF50'),
        yaxis2=dict(
            title='Price (EUR/kWh)',
            overlaying='y',
            side='right',
            linecolor='#9C27B0'
        ),
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1, xanchor='right', x=1),
        template='plotly_white'
    )

    return fig


def create_cost_savings_plot(daily_costs, savings):
    """Create an improved cost comparison plot."""
    merged_data = pd.merge(
        daily_costs,
        savings,
        left_on='date',
        right_on='timestamp',
        how='outer'
    )
    merged_data['cost_with_battery'] = merged_data['cost'] - merged_data['savings']

    fig = go.Figure()

    # Regular cost
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost'],
        name='Regular Cost',
        line=dict(color='#F44336', width=2),
        mode='lines'
    ))

    # Cost with battery
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_battery'],
        name='Cost with Battery',
        line=dict(color='#4CAF50', width=2, dash='dot'),
        mode='lines'
    ))

    # Savings area
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost'],
        fill=None,
        mode='lines',
        line_color='rgba(0,0,0,0)',
        showlegend=False
    ))

    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_battery'],
        fill='tonexty',
        mode='lines',
        line_color='rgba(0,0,0,0)',
        fillcolor='rgba(76, 175, 80, 0.2)',
        name='Savings'
    ))

    fig.update_layout(
        title='Cost Comparison: Regular vs. Battery',
        xaxis_title='Date',
        yaxis_title='Cost (EUR)',
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1, xanchor='right', x=1),
        template='plotly_white'
    )

    return fig

