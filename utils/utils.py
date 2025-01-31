from datetime import datetime
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from modules.kenter_module import KenterAPI


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

def get_meter_hierarchy():
    """Retrieve and cache meter structure with connection -> metering points mapping"""
    if 'meter_hierarchy' not in st.session_state:
        try:
            api = KenterAPI()
            meter_data = api.get_meter_list()
            hierarchy = {}
            
            for connection in meter_data:
                conn_id = connection.get('connectionId')
                if not conn_id:
                    continue
                
                hierarchy[conn_id] = []
                for mp in connection.get('meteringPoints', []):
                    mp_id = mp.get('meteringPointId')
                    if mp_id:
                        hierarchy[conn_id].append(mp_id)
            
            st.session_state.meter_hierarchy = hierarchy
        except Exception as e:
            st.error(f"Error fetching meter data: {str(e)}")
            st.session_state.meter_hierarchy = {}
    
    return st.session_state.meter_hierarchy

### PLOTTING FUNCTIONS ###

def create_plot(usage_df, price_df):
    """Create an interactive plot showing energy flow and prices with clear labeling"""
    fig = go.Figure()

    # Energy Supply (Consumption)
    supply_df = usage_df[usage_df['type'] == 'supply']
    fig.add_trace(go.Scatter(
        x=supply_df['timestamp'],
        y=supply_df['value'],
        name='Energy Used from Grid',
        line=dict(color='#E74C3C', width=2),  # Red for grid consumption
        hovertemplate="%{x|%b %d %H:%M}<br>%{y:.1f} kWh<extra></extra>"
    ))

    # Energy Return (Solar Production)
    return_df = usage_df[usage_df['type'] == 'return']
    fig.add_trace(go.Scatter(
        x=return_df['timestamp'],
        y=return_df['value'],
        name='Solar Energy Produced',
        line=dict(color='#2ECC71', width=2),  # Green for solar
        hovertemplate="%{x|%b %d %H:%M}<br>%{y:.1f} kWh<extra></extra>"
    ))

    # Electricity Prices (Right Axis)
    fig.add_trace(go.Scatter(
        x=price_df['timestamp'],
        y=price_df['price'],
        name='Electricity Price',
        line=dict(color='#3498DB', width=2, dash='dot'),  # Blue for price
        yaxis='y2',
        hovertemplate="%{x|%b %d %H:%M}<br>€%{y:.3f}/kWh<extra></extra>"
    ))

    fig.update_layout(
        title=dict(
            text="<b>Energy Flow & Electricity Prices</b><br>"
                 "<span style='font-size:0.9em'>Grid consumption vs solar production with market prices</span>",
            x=0.05,
            xanchor='left'
        ),
        xaxis=dict(
            title="Date/Time",
            gridcolor='#F0F0F0',
            showgrid=True
        ),
        yaxis=dict(
            title=dict(text="Energy (kWh)", font=dict(color='#2ECC71')),
            gridcolor='#F0F0F0',
            showgrid=True
        ),
        yaxis2=dict(
            title=dict(text="Price (€/kWh)", font=dict(color='#3498DB')),
            overlaying='y',
            side='right',
            showgrid=False
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0
        ),
        hovermode="x unified",
        template="plotly_white",
        margin=dict(t=100),
        plot_bgcolor='white'
    )
    
    # Add annotation explaining solar production
    fig.add_annotation(
        text="↑ Solar production reduces grid energy needs",
        xref="paper", yref="paper",
        x=0.05, y=0.95,
        showarrow=False,
        font=dict(color='#2ECC71', size=10)
    )
    
    return fig


def create_cost_savings_plot(daily_costs, savings):
    """Create an interactive cost comparison plot with clear savings visualization"""
    merged_data = pd.merge(
        daily_costs,
        savings,
        left_on='date',
        right_on='timestamp',
        how='outer'
    )
    merged_data['cost_with_battery'] = merged_data['cost'] - merged_data['savings']

    fig = go.Figure()

    # Original Costs
    fig.add_trace(go.Bar(
        x=merged_data['date'],
        y=merged_data['cost'],
        name='Cost Without Battery',
        marker_color='#E74C3C',  # Red for original costs
        hovertemplate="%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Costs with Battery (Overlay)
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_battery'],
        name='Cost With Battery',
        line=dict(color='#2ECC71', width=3),  # Green for savings
        mode='lines+markers',
        hovertemplate="%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    fig.update_layout(
        title=dict(
            text="Daily Energy Costs: With vs. Without Battery",
            x=0.05,
            xanchor='left'
        ),
        xaxis=dict(
            title="Date",
        ),
        yaxis=dict(
            title="Cost (€)",
        ),
        barmode='overlay',
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0
        ),
        template="plotly_white",
        margin=dict(t=100),
        plot_bgcolor='#f6f4f1'
    )

    # Add savings annotation
    total_savings = merged_data['savings'].sum()
    fig.add_annotation(
        text=f"Total Potential Savings: €{total_savings:.2f}",
        xref="paper", yref="paper",
        x=0.05, y=0.95,
        showarrow=False,
        font=dict(color='#2ECC71', size=12)
    )

    return fig