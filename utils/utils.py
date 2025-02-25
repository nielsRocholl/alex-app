from datetime import datetime
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from modules.kenter_module import KenterAPI
from plotly.subplots import make_subplots


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


def calculate_daily_costs(usage_df, price_df, tax_df=None):
    """Calculate the daily energy costs including network tax if provided."""
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
    
    # Calculate energy cost per interval
    costs['energy_cost'] = costs['value'] * costs['price']
    
    # Add tax if provided
    if tax_df is not None:
        tax_df = tax_df.copy()
        tax_df['timestamp'] = pd.to_datetime(tax_df['timestamp'])
        costs = pd.merge(costs, tax_df[['timestamp', 'tax_amount']], on='timestamp', how='left')
        costs['tax'] = costs['tax_amount']
    else:
        costs['tax'] = 0
    
    # Calculate total cost
    costs['cost'] = costs['energy_cost'] + costs['tax']
    
    # Group by date
    costs['date'] = costs['timestamp'].dt.date
    daily_costs = costs.groupby('date').agg({
        'cost': 'sum',
        'energy_cost': 'sum',
        'tax': 'sum'
    }).reset_index()
    
    return daily_costs

def get_meter_hierarchy():
    """Retrieve and cache meter structure with formatted connection name -> (connection_id, main_metering_point, gtv) mapping"""
    if 'meter_hierarchy' not in st.session_state:
        try:
            api = KenterAPI()
            meter_data = api.get_meter_list()
            gtv_info = api.get_gtv_info()
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

                # Get connection name details and GTV info
                connection_name = conn_id  # default if no name found
                if connection.get('meteringPoints'):
                    master_data = connection['meteringPoints'][0].get('masterData', [{}])[0]
                    bp_code = master_data.get('bpCode', '')
                    bp_name = master_data.get('bpName', '')
                    if bp_code and bp_name:
                        connection_name = f"{bp_code} - {bp_name}"

                # Get GTV info for this connection
                gtv_data = gtv_info.get(conn_id, {})
                
                hierarchy[connection_name] = {
                    'connection_id': conn_id,
                    'main_meter': main_mp,
                    'gtv': gtv_data.get('gtv'),
                    'address': gtv_data.get('address'),
                    'city': gtv_data.get('city')
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
        line=dict(color='#FF6B6B', width=2),  # Coral for grid consumption (matching cost savings chart)
        hovertemplate="%{x|%b %d %H:%M}<br>%{y:.1f} kWh<extra></extra>"
    ))

    # Energy Return (Solar Production)
    return_df = usage_df[usage_df['type'] == 'return']
    fig.add_trace(go.Scatter(
        x=return_df['timestamp'],
        y=return_df['value'],
        name='Solar Energy Produced',
        line=dict(color='#4361EE', width=2),  # Blue for solar (matching cost savings chart)
        hovertemplate="%{x|%b %d %H:%M}<br>%{y:.1f} kWh<extra></extra>"
    ))

    # Electricity Prices (Right Axis)
    fig.add_trace(go.Scatter(
        x=price_df['timestamp'],
        y=price_df['price'],
        name='Electricity Price',
        line=dict(color='#2EC4B6', width=2, dash='dot'),  # Teal for price (matching trend line)
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
            showgrid=False
        ),
        yaxis=dict(
            title=dict(text="Energy (kWh)", font=dict(color='#4361EE')),
            gridcolor='#F0F0F0',
            showgrid=False
        ),
        yaxis2=dict(
            title=dict(text="Price (€/kWh)", font=dict(color='#2EC4B6')),
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
        plot_bgcolor='#f6f4f1',
        paper_bgcolor='#f6f4f1'
    )
    
    # Add annotation explaining solar production
    fig.add_annotation(
        text="↑ Solar production reduces grid energy needs",
        xref="paper", yref="paper",
        x=0.05, y=0.95,
        showarrow=False,
        font=dict(color='#4361EE', size=10)
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
            color='#FF6B6B',  # Coral for current costs
            opacity=0.8
        ),
        hovertemplate="<b>Current Cost</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Cost with only grid arbitrage
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_grid_arbitrage'],
        name='With Grid Arbitrage',
        line=dict(color='#2EC4B6', width=3, dash='dash'),  # Teal for grid arbitrage
        mode='lines+markers',
        marker=dict(
            symbol='circle',
            size=8,
            color='#2EC4B6',
            line=dict(color='white', width=1)
        ),
        hovertemplate="<b>With Grid Arbitrage</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Cost with only solar optimization
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['cost_with_solar_only'],
        name='With Solar Storage',
        line=dict(color='#4361EE', width=3, dash='dot'),  # Blue for solar storage
        mode='lines+markers',
        marker=dict(
            symbol='diamond',
            size=8,
            color='#4361EE',
            line=dict(color='white', width=1)
        ),
        hovertemplate="<b>With Solar Storage</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>"
    ))

    # Final cost after all optimizations
    fig.add_trace(go.Scatter(
        x=merged_data['date'],
        y=merged_data['final_cost'],
        name='Final Cost',
        line=dict(color='#38B000', width=3),  # Green for final cost
        mode='lines+markers',
        marker=dict(
            symbol='square',
            size=8,
            color='#38B000',
            line=dict(color='white', width=1)
        ),
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


def create_cost_savings_plot_v2(daily_costs, savings):
    """Create an enhanced visualization of cost savings using subplots for clarity"""
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
    
    # Calculate daily savings for the waterfall
    merged_data['solar_savings'] = merged_data['net_savings']
    merged_data['grid_savings'] = merged_data['grid_arbitrage_savings']
    merged_data['lost_revenue'] = merged_data['lost_revenue']
    merged_data['total_savings'] = merged_data['solar_savings'] + merged_data['grid_savings'] - merged_data['lost_revenue']
    
    # Create figure with subplots
    fig = make_subplots(
        rows=2, 
        cols=1,
        row_heights=[0.55, 0.45],  # Give more space to bottom plot
        vertical_spacing=0.2,  # Increase spacing between plots
        subplot_titles=("Daily Cost Comparison", "Total Savings Breakdown")
    )

    # Top plot: Daily costs comparison
    fig.add_trace(
        go.Bar(
            x=merged_data['date'],
            y=merged_data['cost'],
            name='Current Cost',
            marker_color='#FF6B6B',  # Coral for current costs
            hovertemplate="<b>Current Cost</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>",
        ),
        row=1, col=1
    )
    
    # Calculate daily savings
    merged_data['daily_savings'] = merged_data['cost'] - merged_data['final_cost']
    
    # Add savings overlay
    fig.add_trace(
        go.Bar(
            x=merged_data['date'],
            y=merged_data['daily_savings'],
            name='Savings with Battery',
            marker_color='#4361EE',  # Blue for savings
            hovertemplate="<b>Daily Savings</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>",
            base=merged_data['final_cost'],  # Start from final cost
        ),
        row=1, col=1
    )

    # Add a line for the final cost
    fig.add_trace(
        go.Scatter(
            x=merged_data['date'],
            y=merged_data['final_cost'],
            name='Final Cost with Battery',
            line=dict(color='#2EC4B6', width=2, dash='dot'),  # Teal for final cost
            hovertemplate="<b>Final Cost</b><br>%{x|%b %d}<br>€%{y:.2f}<extra></extra>",
        ),
        row=1, col=1
    )

    # Bottom plot: Daily savings breakdown
    colors = ['#4361EE', '#2EC4B6', '#FF6B6B']  # Blue, Teal, Coral
    savings_data = [
        ('Solar Storage Savings', merged_data['solar_savings'].sum()),
        ('Grid Arbitrage Savings', merged_data['grid_savings'].sum()),
        ('Lost Solar Revenue', -merged_data['lost_revenue'].sum())
    ]
    
    # Create waterfall chart for savings
    fig.add_trace(
        go.Waterfall(
            name="Savings Breakdown",
            orientation="v",
            measure=["relative", "relative", "relative", "total"],
            x=["Solar Storage<br>Savings", "Grid Arbitrage<br>Savings", "Lost Solar<br>Revenue", "Total<br>Savings"],
            textposition=["inside", "inside", "inside", "inside"],
            text=[f"€{val:.2f}" for val in [
                savings_data[0][1],
                savings_data[1][1],
                savings_data[2][1],
                sum(x[1] for x in savings_data)
            ]],
            y=[
                savings_data[0][1],
                savings_data[1][1],
                savings_data[2][1],
                0
            ],
            connector={"line": {"color": "#2EC4B6"}},  # Teal for connectors
            decreasing={"marker": {"color": "#FF6B6B"}},  # Coral for negative
            increasing={"marker": {"color": "#4361EE"}},  # Blue for positive
            totals={"marker": {"color": "#38B000"}},      # Green for total savings
            textfont=dict(
                size=12,
                color='white',  # White text for better contrast
                family="Arial"
            ),
            hovertemplate="<b>%{x}</b><br>€%{y:.2f}<extra></extra>"
        ),
        row=2, col=1
    )

    # Update layout
    fig.update_layout(
        title=dict(
            text="<b>Battery Storage Cost Analysis</b>",
            x=0.5,
            xanchor='center',
            font=dict(size=20)
        ),
        showlegend=True,
        plot_bgcolor='#f6f4f1',
        paper_bgcolor='#f6f4f1',
        height=900,
        margin=dict(t=100, l=80, r=80, b=80),
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
        barmode='overlay',  # Ensure bars overlay each other
        bargap=0.15        # Gap between bars
    )

    # Update axes and subplot-specific settings
    fig.update_xaxes(
        showgrid=False,
        showline=True,
        linecolor='rgba(0,0,0,0.2)',
        row=1, col=1
    )
    fig.update_yaxes(
        title="Daily Cost (€)",
        showgrid=False,
        showline=True,
        linecolor='rgba(0,0,0,0.2)',
        titlefont=dict(size=14),
        row=1, col=1
    )
    fig.update_yaxes(
        title="Savings (€)",
        showgrid=False,
        showline=True,
        linecolor='rgba(0,0,0,0.2)',
        titlefont=dict(size=14),
        row=2, col=1
    )

    # Update the first subplot to use grouped bars
    fig.update_layout({
        'barmode': 'group',
        'bargap': 0.15,
        'bargroupgap': 0.1
    })

    return fig


def create_echarts_cost_savings_plot(daily_costs, savings):
    """Create an enhanced visualization of cost savings using ECharts"""
    import json
    import numpy as np
    
    # Merge data frames
    merged_data = pd.merge(
        daily_costs,
        savings,
        left_on='date',
        right_on='timestamp',
        how='outer'
    )
    
    # Drop rows with NaN values to ensure clean data
    merged_data = merged_data.dropna(subset=['cost', 'net_savings', 'grid_arbitrage_savings'])
    
    # Calculate different cost scenarios
    merged_data['cost_with_solar_only'] = merged_data['cost'] - merged_data['net_savings']
    merged_data['cost_with_grid_arbitrage'] = merged_data['cost'] - merged_data['grid_arbitrage_savings']
    merged_data['final_cost'] = merged_data['cost_with_solar_only'] - merged_data['grid_arbitrage_savings']
    merged_data['daily_savings'] = merged_data['cost'] - merged_data['final_cost']
    
    # Calculate 7-day moving average of daily savings
    window_size = min(7, len(merged_data))
    if window_size > 0:
        merged_data['savings_ma'] = merged_data['daily_savings'].rolling(window=window_size, min_periods=1).mean()
    else:
        merged_data['savings_ma'] = merged_data['daily_savings']
    
    # Format dates for display
    x_data = [d.strftime('%b %d') for d in merged_data['date']]
    
    # Convert numeric data to lists, ensuring each value is a simple number 
    # with no NaN or special formats that would break JSON
    def safe_list(series):
        return [round(float(x), 2) if pd.notna(x) else 0 for x in series]
    
    current_cost = safe_list(merged_data['cost'])
    final_cost = safe_list(merged_data['final_cost'])
    daily_savings = safe_list(merged_data['daily_savings'])
    savings_trend = safe_list(merged_data['savings_ma'])
    
    # Modern colors for 2025 tech aesthetic
    color_current = '#FF6B6B'  # Vibrant coral for current costs
    color_final = '#4361EE'    # Rich blue for final costs
    color_trend = '#2EC4B6'    # Modern teal for trend line
    
    # Calculate savings percentage for each day
    savings_pct = []
    for i in range(len(current_cost)):
        if current_cost[i] > 0:
            pct = round((current_cost[i] - final_cost[i]) / current_cost[i] * 100, 1)
            savings_pct.append(pct)
        else:
            savings_pct.append(0)
    
    # Create the basic ECharts option structure with minimal complexity
    options = {
        "backgroundColor": '#f6f4f1',  # Match app background color
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {
                "type": "shadow",
                "shadowStyle": {
                    "color": "rgba(0, 0, 0, 0.1)"
                }
            },
            "backgroundColor": "rgba(255, 255, 255, 0.9)",
            "borderWidth": 0,
            "textStyle": {
                "color": "#333"
            }
        },
        "legend": {
            "data": ["Current Cost", "Final Cost", "Savings Trend"],
            "selected": {
                "Current Cost": True,
                "Final Cost": True,
                "Savings Trend": True
            },
            "icon": "circle",
            "textStyle": {
                "fontSize": 12,
                "color": "#333"
            },
            "itemGap": 20,
            "itemWidth": 10,
            "itemHeight": 10
        },
        "grid": {
            "left": "3%", 
            "right": "4%", 
            "bottom": "15%", 
            "top": "15%", 
            "containLabel": True
        },
        "xAxis": {
            "type": "category",
            "data": x_data,
            "axisTick": {"alignWithLabel": True},
            "axisLabel": {
                "rotate": 30,
                "interval": 0,
                "fontSize": 11,
                "color": "#666"
            },
            "axisLine": {
                "lineStyle": {
                    "color": "#ccc"
                }
            },
            "splitLine": {
                "show": False  # Remove grid lines
            }
        },
        "yAxis": {
            "type": "value",
            "name": "Cost (€)",
            "nameTextStyle": {
                "fontSize": 12,
                "color": "#666"
            },
            "axisLabel": {
                "formatter": "€{value}",
                "fontSize": 11,
                "color": "#666"
            },
            "splitLine": {
                "show": False  # Remove grid lines
            }
        },
        "series": [
            {
                "name": "Current Cost",
                "type": "bar",
                "barWidth": "50%",
                "itemStyle": {
                    "color": color_current,
                    "borderRadius": [8, 8, 0, 0]  # Curved top corners
                },
                "data": current_cost,
                "tooltip": {
                    "formatter": "{b}<br>Original: <b>€{c}</b>"
                }
            },
            {
                "name": "Final Cost",
                "type": "line",
                "smooth": True,
                "symbol": "circle",
                "symbolSize": 8,
                "lineStyle": {
                    "width": 3, 
                    "color": color_final,
                    "shadowColor": "rgba(0, 0, 0, 0.2)",
                    "shadowBlur": 8
                },
                "itemStyle": {
                    "color": color_final,
                    "borderWidth": 2,
                    "borderColor": "#fff"
                },
                "data": final_cost,
                "tooltip": {
                    "formatter": "{b}<br>With Battery: <b>€{c}</b>"
                }
            },
            {
                "name": "Savings",
                "type": "bar",
                "stack": "savings",
                "barGap": "-100%",  # Overlay on the current cost bars
                "itemStyle": {
                    "color": "transparent",  # Make the bar invisible
                    "borderWidth": 0
                },
                "emphasis": {
                    "itemStyle": {
                        "color": "transparent"  # Keep invisible on hover
                    }
                },
                "data": current_cost,
                "tooltip": {
                    "formatter": "{b}<br>Savings: <b>€{c}</b>"
                }
            },
            {
                "name": "Savings Trend",
                "type": "line",
                "smooth": True,
                "symbol": "none",
                "lineStyle": {
                    "width": 3, 
                    "color": color_trend
                },
                "itemStyle": {
                    "color": color_trend
                },
                "data": savings_trend,
                "tooltip": {
                    "formatter": "{b}<br>Avg Savings: <b>€{c}</b>"
                }
            }
        ],
        "dataZoom": [{
            "type": "slider",
            "show": len(x_data) > 10,
            "height": 20,
            "bottom": 10,
            "start": 0,
            "end": 100,
            "borderColor": "rgba(0,0,0,0)",
            "backgroundColor": "rgba(0,0,0,0.05)",
            "fillerColor": "rgba(67, 97, 238, 0.2)",
            "handleStyle": {
                "color": color_final
            }
        }],
        "toolbox": {
            "feature": {
                "saveAsImage": {
                    "title": "Save as Image",
                    "pixelRatio": 2
                },
                "dataZoom": {},
                "restore": {}
            },
            "right": 15,
            "itemSize": 15,
            "itemGap": 5,
            "iconStyle": {
                "borderWidth": 0,
                "borderColor": "#ccc",
                "color": "#666"
            }
        },
        "animation": True,
        "animationDuration": 1000,
        "animationEasing": "cubicOut"
    }
    
    return options

def create_savings_breakdown_chart(savings):
    """Create a waterfall chart showing the breakdown of savings components"""
    import numpy as np
    
    # Calculate total values
    total_solar_savings = savings['net_savings'].sum()
    total_grid_savings = savings['grid_arbitrage_savings'].sum()
    total_lost_revenue = savings['lost_revenue'].sum()
    total_net_savings = total_solar_savings + total_grid_savings - total_lost_revenue
    
    # Format values for display
    def format_value(val):
        return round(float(val), 2)
    
    solar_savings = format_value(total_solar_savings)
    grid_savings = format_value(total_grid_savings)
    lost_revenue = format_value(total_lost_revenue)
    net_savings = format_value(total_net_savings)
    
    # Modern colors
    color_solar = '#4361EE'    # Blue for solar savings
    color_grid = '#2EC4B6'     # Teal for grid savings
    color_lost = '#FF6B6B'     # Coral for lost revenue
    color_total = '#38B000'    # Green for total
    
    # Create ECharts options
    options = {
        "backgroundColor": '#f6f4f1',  # Match app background color
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {
                "type": "shadow"
            },
            "formatter": "{b}: <b>€{c}</b>"
        },
        "grid": {
            "left": "3%",
            "right": "4%",
            "bottom": "3%",
            "top": "60px",
            "containLabel": True
        },
        "xAxis": {
            "type": "category",
            "data": ["Solar Savings", "Grid Arbitrage", "Lost Revenue", "Net Savings"],
            "axisLabel": {
                "interval": 0,
                "fontSize": 12,
                "color": "#666",
                "rotate": 0
            },
            "splitLine": {
                "show": False  # Remove grid lines
            }
        },
        "yAxis": {
            "type": "value",
            "name": "Amount (€)",
            "nameTextStyle": {
                "fontSize": 12,
                "color": "#666"
            },
            "axisLabel": {
                "formatter": "€{value}",
                "fontSize": 11,
                "color": "#666"
            },
            "splitLine": {
                "show": False  # Remove grid lines
            }
        },
        "series": [
            {
                "name": "Savings",
                "type": "bar",
                "stack": "total",
                "label": {
                    "show": True,
                    "position": "inside",
                    "formatter": "€{c}",
                    "fontSize": 12,
                    "fontWeight": "bold",
                    "color": "#fff"
                },
                "itemStyle": {
                    "borderRadius": [8, 8, 0, 0]  # Curved top corners for positive values
                },
                "data": [
                    {
                        "value": solar_savings,
                        "itemStyle": {
                            "color": color_solar,
                            "borderRadius": [8, 8, 0, 0]  # Curved top corners
                        }
                    },
                    {
                        "value": grid_savings,
                        "itemStyle": {
                            "color": color_grid,
                            "borderRadius": [8, 8, 0, 0]  # Curved top corners
                        }
                    },
                    {
                        "value": -lost_revenue,
                        "itemStyle": {
                            "color": color_lost,
                            "borderRadius": [0, 0, 8, 8]  # Curved bottom corners for negative values
                        }
                    },
                    {
                        "value": net_savings,
                        "itemStyle": {
                            "color": color_total,
                            "borderRadius": [8, 8, 0, 0]  # Curved top corners
                        }
                    }
                ]
            }
        ],
        "animationEasing": "elasticOut"
    }
    
    return options