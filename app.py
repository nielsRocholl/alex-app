import streamlit as st
from modules.kenter_module import get_kenter_data
from modules.entsoe_module import get_energy_prices
from modules.battery_module import BatterySavingsCalculator
from modules.tax_module import NetworkTaxCalculator
from utils.utils import *
from auth.authenticator import Authenticator
from datetime import datetime
import plotly.graph_objects as go
from streamlit_echarts import st_echarts
import pandas as pd

# Set page configuration
st.set_page_config(
    page_title="Energy Analyzer",
    page_icon="⚡",
    layout="wide"
)

# Initialize the Authenticator
allowed_users = st.secrets["ALLOWED_USERS"].split(",")
authenticator = Authenticator(
    allowed_users=allowed_users,
    token_key=st.secrets["TOKEN_KEY"],
    client_secret=st.secrets["CLIENT_SECRET"],
    redirect_uri= "https://mango2mango.streamlit.app/" #"http://localhost:8501" #
)

def recalculate_savings(battery_capacity, enable_grid_arbitrage, enable_solar_arbitrage):
    """Recalculate savings without fetching new data"""
    if 'report_data' not in st.session_state:
        return
    
    # Get cached data
    usage_df = st.session_state.report_data['usage_df']
    price_df = st.session_state.report_data['price_df']
    
    # Recalculate savings
    battery_calculator = BatterySavingsCalculator(
        battery_capacity=battery_capacity,
        enable_grid_arbitrage=enable_grid_arbitrage,
        enable_solar_arbitrage=enable_solar_arbitrage
    )
    savings = battery_calculator.arbitrage(usage_df, price_df)
    
    # Update session state
    st.session_state.report_data['savings'] = savings

def main():
    st.title("⚡ Energy Analyzer")
    authenticator.check_auth()

    # Show login/logout buttons in the sidebar
    with st.sidebar:
        if st.session_state.get("connected"):
            if st.button("Log out", use_container_width=True):
                authenticator.logout()
                st.rerun()
            
            st.subheader("Analysis Settings")
            
            # Network Operator Selection
            network_operator = st.selectbox(
                "Network Operator",
                options=NetworkTaxCalculator.NETWORK_OPERATORS,
                index=0,
                help="Select your network operator for tax calculations"
            )
            
            # Battery capacity input
            battery_capacity = st.number_input(
                "Battery Capacity (kWh)",
                min_value=1,
                max_value=1000,
                value=100,
                step=1,
                format="%d",
                help="Enter the capacity of your battery storage system in kWh"
            )
            
            enable_solar_arbitrage = st.toggle(
                "Enable Solar Storage",
                value=True,
                help="Store excess solar energy to use during expensive periods"
            )
            enable_grid_arbitrage = st.toggle(
                "Enable Grid Arbitrage",
                value=True,
                help="Buy cheap grid energy to use during expensive periods"
            )
            
            # If any settings change and we have data, recalculate
            if 'report_data' in st.session_state:
                current_settings = (
                    battery_capacity,
                    enable_grid_arbitrage,
                    enable_solar_arbitrage
                )
                if 'last_settings' not in st.session_state:
                    st.session_state.last_settings = current_settings
                
                if current_settings != st.session_state.last_settings:
                    recalculate_savings(battery_capacity, enable_grid_arbitrage, enable_solar_arbitrage)
                    st.session_state.last_settings = current_settings
            
            # Plot selection
            selected_plots = st.multiselect(
                "Choose visualizations to display:",
                options=["Energy Flow & Prices", "Cost Savings"],
                default=["Cost Savings"],
                help="Select which charts to show in the analysis"
            )
            
            st.markdown("---")
            st.subheader("Meter Selection")
            meter_hierarchy = get_meter_hierarchy()

            # Connection selection with formatted names
            connection_names = list(meter_hierarchy.keys())
            selected_conn_name = st.selectbox(
                "Connection Point",
                options=connection_names,
                index=0,
                help="Select your facility's connection point",
                on_change=clear_report_state
            )

            # Get connection details automatically
            if selected_conn_name:
                conn_details = meter_hierarchy[selected_conn_name]
                connection_id = conn_details['connection_id']
                main_meter = conn_details['main_meter']
        else:
            auth_url = authenticator.get_auth_url()
            st.link_button("Login with Google", auth_url, use_container_width=True)

    # Main content for authenticated users
    if st.session_state.get("connected"):
        st.write(f"Welcome, {st.session_state['user_info'].get('email', 'User')}! 👋")
        st.markdown("---")

        # Date inputs
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", help="Select analysis start date")
        with col2:
            end_date = st.date_input("End Date", help="Select analysis end date")

        # Initialize the show_report state if it doesn't exist
        if 'show_report' not in st.session_state:
            st.session_state.show_report = False

        # Add generate report button
        if st.button("🚀 Generate Report"):
            st.session_state.show_report = True
            if start_date and end_date and selected_conn_name:
                valid, error_message = validate_dates(start_date, end_date)
                if not valid:
                    st.error(error_message)
                    st.session_state.show_report = False
                    return
                
                try:
                    with st.spinner('Crunching numbers...'):
                        # Fetch data
                        usage_df = get_kenter_data(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d'),
                            connection_id=connection_id,
                            metering_point=main_meter,
                            interval='15min'
                        )
                        
                        price_df = get_energy_prices(
                            start_date.strftime('%Y-%m-%d'),
                            end_date.strftime('%Y-%m-%d')
                        )
                        
                        # Get GTV for tax calculation
                        gtv_str = conn_details.get('gtv', 'N/A')
                        try:
                            gtv = float(gtv_str)
                        except (ValueError, TypeError):
                            st.warning("⚠️ Could not determine GTV for tax calculations. Using default high rate.")
                            gtv = 0  # This will result in using the low_gtv (higher) tax rate
                        
                        # Calculate network tax
                        tax_calculator = NetworkTaxCalculator()
                        tax_df = tax_calculator.calculate_tax(
                            usage_df,
                            network_operator,
                            gtv
                        )
                        
                        # Calculate metrics including tax
                        daily_costs = calculate_daily_costs(usage_df, price_df, tax_df)
                        battery_calculator = BatterySavingsCalculator(
                            battery_capacity=battery_capacity,
                            enable_grid_arbitrage=enable_grid_arbitrage,
                            enable_solar_arbitrage=enable_solar_arbitrage
                        )
                        savings = battery_calculator.arbitrage(usage_df, price_df)
                        
                        # Store results in session state
                        st.session_state.report_data = {
                            'usage_df': usage_df,
                            'price_df': price_df,
                            'tax_df': tax_df,
                            'daily_costs': daily_costs,
                            'savings': savings,
                            'generated_at': datetime.now()
                        }
                        
                except Exception as e:
                    if 'timestamp' in str(e):
                        st.error("No data available for selected meter")
                    else:
                        st.error(f"Error generating report: {str(e)}")
                    st.session_state.show_report = False
                    st.session_state.pop('report_data', None)
                    return

        # Display report if show_report is True and we have data
        if st.session_state.show_report and 'report_data' in st.session_state:
            report_data = st.session_state.report_data
            usage_df = report_data['usage_df']
            price_df = report_data['price_df']
            tax_df = report_data['tax_df']
            daily_costs = report_data['daily_costs']
            savings = report_data['savings']
            
            # Show selected visualizations
            if "Energy Flow & Prices" in selected_plots:
                st.markdown("## 📈 Energy Flow & Electricity Prices")
                fig = create_plot(usage_df, price_df)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("---")
            
            if "Cost Savings" in selected_plots:
                st.markdown("## 💰 Battery Savings Potential")
                
                # Display contextual information above the chart
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown("""
                    This chart shows your **daily energy costs** with and without a battery system.
                    - The <span style='color: #FF6B6B; font-weight: bold;'>coral bars</span> show your current costs
                    - The <span style='color: #4361EE; font-weight: bold;'>blue line</span> shows your costs after battery savings
                    - The <span style='color: #2EC4B6; font-weight: bold;'>teal trend line</span> shows the savings pattern over time
                    """, unsafe_allow_html=True)
                with col2:
                    total_savings = (savings['net_savings'].sum() + savings['grid_arbitrage_savings'].sum() - savings['lost_revenue'].sum())
                    avg_daily_savings = total_savings / len(daily_costs) if len(daily_costs) > 0 else 0
                    st.metric("Average Daily Savings", f"€{avg_daily_savings:.2f}")
                
                # Create the ECharts options
                echarts_options = create_echarts_cost_savings_plot(daily_costs, savings)
                
                # Add a wrapper for the chart with better padding
                st.markdown('<div style="padding: 1rem 0;">', unsafe_allow_html=True)
                
                # Display the chart with additional height for better visualization
                with st.container():
                    try:
                        st_echarts(options=echarts_options, height="500px", key="cost_savings_chart")
                    except Exception as e:
                        st.error(f"Error displaying ECharts: {str(e)}")
                        
                        # Fallback to plotly
                        st.info("Displaying fallback visualization...")
                        merged_data = pd.merge(
                            daily_costs,
                            savings,
                            left_on='date',
                            right_on='timestamp',
                            how='outer'
                        )
                        
                        # Calculate final cost
                        merged_data['final_cost'] = merged_data['cost'] - merged_data['net_savings'] - merged_data['grid_arbitrage_savings']
                        
                        # Create a simple plotly bar chart
                        fig = go.Figure()
                        
                        # Add original cost bars
                        fig.add_trace(go.Bar(
                            x=merged_data['date'],
                            y=merged_data['cost'],
                            name='Current Cost',
                            marker_color='#FF6B6B'
                        ))
                        
                        # Add final cost line
                        fig.add_trace(go.Scatter(
                            x=merged_data['date'],
                            y=merged_data['final_cost'],
                            name='Final Cost',
                            line=dict(color='#4361EE', width=3)
                        ))
                        
                        fig.update_layout(
                            title="Daily Cost Comparison",
                            xaxis_title="Date",
                            yaxis_title="Cost (€)",
                            legend_title="Legend",
                            height=500,
                            template="plotly_white"
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                
                st.markdown('</div>', unsafe_allow_html=True)
                st.markdown("---")
                
                # Add the savings breakdown chart
                st.markdown("## 📊 Savings Breakdown")
                st.markdown("""
                This chart shows how your savings are calculated:
                - **Solar Savings**: Money saved by using stored solar energy
                - **Grid Arbitrage**: Money saved by buying cheap electricity and using it during expensive periods
                - **Lost Revenue**: Money you could have earned by selling excess solar energy back to the grid
                - **Net Savings**: Your total savings after all factors are considered
                """)
                
                # Create the savings breakdown chart
                breakdown_options = create_savings_breakdown_chart(savings)
                
                # Display the chart
                try:
                    st_echarts(options=breakdown_options, height="400px", key="savings_breakdown_chart")
                except Exception as e:
                    st.error(f"Error displaying savings breakdown chart: {str(e)}")
            
            # Key metrics cards with tax information
            st.markdown("### 📊 Your Battery Savings Potential")
            total_costs = daily_costs['cost'].sum()
            total_tax = daily_costs['tax'].sum()
            total_energy_cost = total_costs - total_tax
            total_gross_savings = savings['gross_savings'].sum()
            total_lost_revenue = savings['lost_revenue'].sum()
            total_net_savings = savings['net_savings'].sum()
            total_grid_arbitrage = savings['grid_arbitrage_savings'].sum()
            total_combined_savings = total_net_savings + total_grid_arbitrage - total_lost_revenue
            savings_percentage = (total_combined_savings / total_costs * 100) if total_costs > 0 else 0
            total_supply = usage_df[usage_df['type'] == 'supply']['value'].sum()
            total_return = usage_df[usage_df['type'] == 'return']['value'].sum()
            avg_price = price_df['price'].mean()
            final_cost = total_costs - total_combined_savings

            # Modern UI with clear sections
            st.markdown("""
            <style>
            .big-font {
                font-size:30px !important;
                font-weight:bold;
            }
            .card {
                border-radius: 10px;
                padding: 20px;
                background-color: white;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            .summary-card {
                text-align: center;
                padding: 15px;
                border-radius: 10px;
                margin-bottom: 10px;
            }
            .highlight {
                color: #1b6cbb;
                font-weight: bold;
            }
            .savings {
                color: #4bb543;
            }
            .costs {
                color: #d97857;
            }
            .neutral {
                color: #5645a1;
            }
            .tooltip-icon {
                color: #aaaaaa;
                font-size: 16px;
                margin-left: 5px;
            }
            .progress-container {
                width: 100%;
                background-color: #f1f1f1;
                border-radius: 5px;
                margin-top: 10px;
                margin-bottom: 15px;
            }
            .progress-bar {
                height: 25px;
                border-radius: 5px;
                text-align: center;
                line-height: 25px;
                color: white;
                font-weight: bold;
            }
            .energy-flow-icon {
                font-size: 40px;
                margin-right: 15px;
                float: left;
            }
            </style>
            """, unsafe_allow_html=True)

            # Executive Summary Card
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<h2>💰 Cost Summary</h2>', unsafe_allow_html=True)
            
            # Progress bar showing cost reduction
            savings_percent = min(int(savings_percentage), 100)  # Cap at 100% for visual
            
            st.markdown(f"""
            <div style="display: flex; align-items: center; margin-bottom: 20px;">
                <div style="flex: 1;">
                    <div class="big-font">Current Costs: <span class="costs">€{total_costs:.2f}</span></div>
                    <div class="big-font">Savings: <span class="savings">€{total_combined_savings:.2f}</span></div>
                    <div class="big-font">Final Costs: <span class="neutral">€{final_cost:.2f}</span></div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 24px; margin-bottom: 10px;">Cost Reduction</div>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: {savings_percent}%; background-color: #4bb543;">
                            {savings_percentage:.1f}%
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Savings Breakdown section
            st.markdown('<h3>💸 Savings Breakdown</h3>', unsafe_allow_html=True)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f"""
                <div class="summary-card" style="background-color: rgba(27, 108, 187, 0.1);">
                    <h4>🌞 Solar Storage</h4>
                    <div style="font-size: 22px;" class="highlight">€{total_net_savings:.2f}</div>
                    <div>Savings from storing your solar energy</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div class="summary-card" style="background-color: rgba(86, 69, 161, 0.1);">
                    <h4>⚡ Grid Arbitrage</h4>
                    <div style="font-size: 22px;" class="highlight">€{total_grid_arbitrage:.2f}</div>
                    <div>Savings from smart grid energy buying</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                st.markdown(f"""
                <div class="summary-card" style="background-color: rgba(217, 120, 87, 0.1);">
                    <h4>📉 Lost Solar Revenue</h4>
                    <div style="font-size: 22px;" class="costs">-€{total_lost_revenue:.2f}</div>
                    <div>Potential income lost from not selling solar back to grid</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Energy Flow & Costs Card
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<h2>⚡ Energy & Cost Details</h2>', unsafe_allow_html=True)
            
            # Current cost breakdown
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<h3>Current Cost Structure</h3>', unsafe_allow_html=True)
                fig = go.Figure()
                fig.add_trace(go.Pie(
                    labels=['Energy Cost', 'Network Tax'],
                    values=[total_energy_cost, total_tax],
                    hole=0.6,
                    marker_colors=['#1b6cbb', '#d97857'],
                    textinfo='label+percent',
                    hoverinfo='label+value+percent',
                    hovertemplate='<b>%{label}</b><br>€%{value:.2f}<br>%{percent}'
                ))
                fig.update_layout(
                    showlegend=False,
                    margin=dict(t=0, b=0, l=0, r=0),
                    annotations=[dict(text=f'€{total_costs:.2f}', x=0.5, y=0.5, font_size=16, showarrow=False)]
                )
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                # GTV Information
                conn_details = meter_hierarchy[selected_conn_name]
                gtv = conn_details.get('gtv', 'N/A')
                
                st.markdown('<h3>Key Energy Metrics</h3>', unsafe_allow_html=True)
                st.markdown(f"""
                <div style="padding: 10px; margin-bottom: 10px;">
                    <div><b>🏢 Contracted Capacity (GTV):</b> {gtv} kW</div>
                    <div style="font-size: 12px; color: #666;">Determines your network costs & capacity</div>
                </div>
                <div style="padding: 10px; margin-bottom: 10px;">
                    <div><b>🔌 Grid Energy Used:</b> {total_supply:.1f} kWh</div>
                    <div style="font-size: 12px; color: #666;">Energy bought from the grid</div>
                </div>
                <div style="padding: 10px; margin-bottom: 10px;">
                    <div><b>🔄 Solar Energy Returned:</b> {total_return:.1f} kWh</div>
                    <div style="font-size: 12px; color: #666;">Energy sold back to the grid</div>
                </div>
                <div style="padding: 10px;">
                    <div><b>💡 Average Electricity Price:</b> €{avg_price:.3f}/kWh</div>
                    <div style="font-size: 12px; color: #666;">Average price paid for grid energy</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # What this means for you
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<h2>🎯 What This Means For You</h2>', unsafe_allow_html=True)
            
            # ROI and simple explanation
            years_to_payback = 5  # This should be calculated based on battery cost and savings
            monthly_savings = total_combined_savings / ((end_date - start_date).days / 30)
            
            st.markdown(f"""
            <div style="display: flex; margin-bottom: 20px;">
                <div class="energy-flow-icon">💰</div>
                <div>
                    <h3>Monthly Savings</h3>
                    <p>With a battery system, you could save approximately <span class="highlight">€{monthly_savings:.2f}</span> per month.</p>
                </div>
            </div>
            
            <div style="display: flex; margin-bottom: 20px;">
                <div class="energy-flow-icon">🔋</div>
                <div>
                    <h3>How It Works</h3>
                    <p>Your battery stores excess solar energy during the day and uses it when electricity prices are high. 
                    It can also buy cheap grid electricity at night to use during expensive periods.</p>
                </div>
            </div>
            
            <div style="display: flex;">
                <div class="energy-flow-icon">📊</div>
                <div>
                    <h3>Grid Independence</h3>
                    <p>Adding a battery gives you more independence from the grid and protects you from rising electricity prices.</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Add location info if available
            if conn_details.get('address') and conn_details.get('city'):
                st.caption(f"📍 Location: {conn_details['address']}, {conn_details['city']}")
            
            # Add refresh button with timestamp
            refresh_col, ts_col = st.columns([1,3])
            with refresh_col:
                if st.button("🔄 Refresh Results", help="Recalculate with latest data"):
                    st.session_state.show_report = False
                    st.rerun()
            with ts_col:
                st.caption(f"Last updated: {report_data['generated_at'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        elif not st.session_state.show_report:
            st.info("Select dates and click 'Generate Report' to begin")
        
    else:
        st.warning("🔒 Please log in to access the energy analyzer")

if __name__ == "__main__":
    main()