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
    """Retrieve and cache meter structure with formatted connection name -> (connection_id, main_metering_point) mapping"""
    if 'meter_hierarchy' not in st.session_state:
        try:
            api = KenterAPI()
            meter_data = api.get_meter_list()
            hierarchy = {}
            
            for connection in meter_data:
                conn_id = connection.get('connectionId')
                if not conn_id:
                    continue

                # Find main metering point
                main_mp = None
                for mp in connection.get('meteringPoints', []):
                    if mp.get('meteringPointType') == 'OP' and mp.get('relatedMeteringPointId') is None:
                        main_mp = mp.get('meteringPointId')
                        break  # Found main point

                # Get connection name details from first metering point's masterData
                connection_name = conn_id  # default if no name found
                if connection.get('meteringPoints'):
                    master_data = connection['meteringPoints'][0].get('masterData', [{}])[0]
                    bp_code = master_data.get('bpCode', '')
                    bp_name = master_data.get('bpName', '')
                    if bp_code and bp_name:
                        connection_name = f"{bp_code} - {bp_name}"

                hierarchy[connection_name] = {
                    'connection_id': conn_id,
                    'main_meter': main_mp
                }

            st.session_state.meter_hierarchy = hierarchy
        except Exception as e:
            st.error(f"Error fetching meter data: {str(e)}")
            st.session_state.meter_hierarchy = {}
    
    return st.session_state.meter_hierarchy

# Function to clear report state when connection changes
def clear_report_state():
    st.session_state.show_report = False
    if 'report_data' in st.session_state:
        del st.session_state.report_data

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
    """Create an intuitive, modern visualization of potential savings"""
    merged_data = pd.merge(
        daily_costs,
        savings,
        left_on='date',
        right_on='timestamp',
        how='outer'
    )
    
    # Calculate different cost scenarios
    merged_data['cost_with_solar_only'] = merged_data['cost'] - merged_data['net_savings']
    merged_data['cost_with_grid_arbitrage'] = merged_data['cost'] - merged_data['grid_arbitrage_savings']
    merged_data['final_cost'] = merged_data['cost_with_solar_only'] - merged_data['grid_arbitrage_savings']
    
    fig = go.Figure()

    # Original cost bars
    fig.add_trace(go.Bar(
        x=merged_data['date'],
        y=merged_data['cost'],
        name='Current Cost',
        marker=dict(
            color='#E74C3C',
            opacity=0.3
        ),
        hovertemplate="<b>Current Cost</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Cost with only grid arbitrage
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_grid_arbitrage'],
        name='With Grid Arbitrage',
        line=dict(color='#3498DB', width=2.5),  # Blue for grid
        mode='lines',
        hovertemplate="<b>With Grid Arbitrage</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Cost with only solar optimization
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_solar_only'],
        name='With Solar Storage',
        line=dict(color='#F39C12', width=2.5),  # Orange for solar
        mode='lines',
        hovertemplate="<b>With Solar Storage</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Final cost after all optimizations
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['final_cost'],
        name='Final Cost',
        line=dict(color='#27AE60', width=3),  # Green for final
        mode='lines',
        hovertemplate="<b>Final Cost</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    fig.update_layout(
        showlegend=True,
        xaxis=dict(
            title=None,
            showgrid=False,
            showline=True,
            linecolor='rgba(0,0,0,0.2)'
        ),
        yaxis=dict(
            title="Daily Cost (€)",
            showgrid=False,
            showline=True,
            linecolor='rgba(0,0,0,0.2)',
            titlefont=dict(size=14)
        ),
        plot_bgcolor='#f6f4f1',
        paper_bgcolor='#f6f4f1',
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='rgba(0,0,0,0.1)',
            borderwidth=1
        ),
        margin=dict(t=40, l=60, r=60, b=40),
        barmode='overlay'
    )

    return fig